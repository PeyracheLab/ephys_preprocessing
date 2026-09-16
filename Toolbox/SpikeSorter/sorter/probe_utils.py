"""
Builds a KiloSort 4 probe dict from a probe JSON file or a fallback layout.

Probe JSON holds GEOMETRY ONLY, in per-shank rank order (position along the
shank — e.g. tip-to-top), never raw channel numbers:
{
    "name": "neuronexus_a1x32",
    "n_channels_per_shank": 32,       # int (uniform shanks), or a list with one
    "n_shanks": 1,                    #   entry per shank for unequal shanks
                                       #   (e.g. Buzsaki64sp: [10,10,10,14,10,10])
    "xc": [...],                      # rank-order geometry: one shank's worth
    "yc": [...]                       #   if n_channels_per_shank is an int, or
                                       #   the full probe concatenated shank-by-
                                       #   shank if it's a list
}

The XML's <anatomicalDescription> groups hold the actual WIRING — which real
channel number sits at each rank position on each shank. This matters because
headstage/adapter wiring is usually NOT sequential: e.g. Toolbox/xml_files/
b32_amplifier.xml lists shank 0 as channels [16, 30, 17, 31, 18, 22, 20, 21],
not [0..7]. So geometry is assigned by ORDER, never by raw channel number:
rank position 0 in the probe's per-shank block goes to whichever channel is
listed FIRST in that shank's XML group (channel 16 above), rank position 1 to
whichever is listed second (channel 30), and so on — regardless of what those
channel numbers actually are. This is the only mechanism in this file; there
is no separate "full geometry indexed by raw channel number" mode, because
that would silently assume sequential per-shank wiring, which real probes
generally don't have.

A fresh XML auto-generated from a probe file (master_preprocessing.py's
_groups_from_probe, used only when no real per-hardware channel-map XML is
available) lists channels sequentially per shank, since it has no wiring
information to go on — geometry from that fallback XML should be treated as
a rough guess, not the real per-channel positions. For anything that matters,
supply a real channel-map XML (as amplifier.xml) analogous to the ones in
Toolbox/xml_files/.

200 µm inter-shank x-offset is applied automatically, per shank index.

Validation
----------
A hard error is raised if:
  - total XML anatomical channels != total probe channels
  - number of XML groups != total probe shanks
  - per-shank XML group sizes != probe's n_channels_per_shank

Discarded channels
------------------
Channels that appear in <anatomicalDescription> but NOT in <spikeDetection>
are included in the channel map but marked connected=False. KiloSort 4
ignores them during sorting but they are preserved for correct .dat indexing.
"""

import json
from pathlib import Path
from typing import List, Optional, Tuple

from .xml_tools import XmlParams


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_probe_dict(
    params: XmlParams,
    probe_names: List[str],
    library_dir: Optional[Path] = None,
    layout: str = "staggered",
    site_spacing: float = 20.0,
    data_dir: Optional[Path] = None,
) -> dict:
    """
    Build a KS4-compatible probe dict.

    Parameters
    ----------
    params       : parsed XML parameters (n_channels, anat_grps, spk_grps)
    probe_names  : list of probe names or file paths (0 or 1 entries)
                   - empty  → auto-detect probe.json in data_dir, else fallback layout
                   - 1 name → single probe covers all XML groups
    library_dir  : directory to search for probe JSON files by name
    layout       : fallback layout if no probe file found ('staggered'|'linear'|'columns')
    site_spacing : fallback inter-electrode distance in µm
    data_dir     : recording directory (checked for probe.json when probe_names is empty)

    Returns
    -------
    dict with keys: chanMap, xc, yc, kcoords, connected, n_chan
    """
    anat_grps = params.anat_grps
    if not anat_grps:
        raise ValueError("XML contains no anatomical channel groups.")

    # Channels present in spk_grps → connected.
    # If spk_grps is empty (no <spikeDetection> block in XML), treat all
    # anatomical channels with skip=0 as connected.
    if params.spk_grps:
        active_channels: set = set()
        for grp in params.spk_grps:
            active_channels.update(grp.channels)
    else:
        active_channels = set()
        for grp in anat_grps:
            for ch, sk in zip(grp.channels, grp.skip):
                if sk == 0:
                    active_channels.add(ch)

    total_anat_channels = sum(len(g.channels) for g in anat_grps)

    # Resolve probe specification
    probes = _resolve_probes(
        probe_names, data_dir, library_dir, layout, site_spacing, anat_grps
    )

    if len(probes) != 1:
        raise NotImplementedError(
            "This version expects a single probe JSON file. "
            "If you need two-probe support, I can add it."
        )

    probe = probes[0]
    probe_name = probe.get("name", "unnamed")

    n_total = params.n_channels
    group_sizes = [len(g.channels) for g in anat_grps]

    shank_counts = _probe_shank_counts(probe)
    total_probe_channels = sum(shank_counts)
    total_probe_shanks = len(shank_counts)

    if total_anat_channels != total_probe_channels:
        raise ValueError(
            f"Channel count mismatch:\n"
            f"  XML anatomical channels : {total_anat_channels}\n"
            f"  Probe file channels      : {total_probe_channels}\n"
            + _probe_summary([probe])
        )

    if len(anat_grps) != total_probe_shanks:
        raise ValueError(
            f"Shank count mismatch:\n"
            f"  XML anatomical groups : {len(anat_grps)}\n"
            f"  Probe file shanks     : {total_probe_shanks}\n"
            + _probe_summary([probe])
        )

    if group_sizes != shank_counts:
        raise ValueError(
            f"XML group sizes {group_sizes} do not match probe shank counts "
            f"{shank_counts}."
        )

    # Per-shank local geometry blocks, in rank order (tip-to-top or whatever
    # convention the probe file uses) — NOT raw channel order. Either one
    # template reused for every shank (uniform n_channels_per_shank), or the
    # full probe's geometry sliced shank-by-shank (a list, e.g. Buzsaki64sp).
    local_blocks = _per_shank_geometry(probe, shank_counts)

    xc = [0.0] * n_total
    yc = [0.0] * n_total
    kcoords = [0] * n_total
    connected = [False] * n_total

    for shank_global, (grp, (block_xc, block_yc)) in enumerate(zip(anat_grps, local_blocks)):
        x_offset = shank_global * 200.0
        for local_idx, ch in enumerate(grp.channels):
            # local_idx is the RANK position within this shank; ch is whatever
            # real channel number the XML lists at that rank (see module
            # docstring — wiring is usually not sequential).
            xc[ch] = block_xc[local_idx] + x_offset
            yc[ch] = block_yc[local_idx]
            kcoords[ch] = shank_global + 1  # 1-indexed shank
            connected[ch] = ch in active_channels

    return {
        "chanMap": list(range(n_total)),
        "xc": xc,
        "yc": yc,
        "kcoords": kcoords,
        "connected": connected,
        "n_chan": n_total,
    }


def load_probe(name_or_path: str, library_dir: Optional[Path] = None) -> dict:
    """Load a probe JSON by file path or by name from the probe library."""
    p = Path(name_or_path)
    if p.suffix.lower() == ".json" and p.exists():
        with open(p) as f:
            return json.load(f)

    if library_dir is None:
        library_dir = _default_library_dir()

    for candidate in [
        library_dir / name_or_path,
        library_dir / f"{name_or_path}.json",
    ]:
        if candidate.exists():
            with open(candidate) as f:
                probe = json.load(f)
            print(f"  Probe loaded: {candidate}")
            return probe

    available = (
        [p.stem for p in library_dir.glob("*.json")]
        if library_dir and library_dir.exists()
        else ["(library not found)"]
    )
    raise FileNotFoundError(
        f"Probe '{name_or_path}' not found as a file or in the probe library.\n"
        f"Library: {library_dir}\n"
        f"Available: {available}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _probe_shank_counts(probe: dict) -> List[int]:
    """
    Return channel counts per shank.

    Supports:
      - n_channels_per_shank as an int
      - n_channels_per_shank as a list, e.g. [10, 11, 11, 11, 11, 10]
      - fallback to counts inferred from kcoords if needed
    """
    ncpp = probe.get("n_channels_per_shank")

    if isinstance(ncpp, list):
        return [int(x) for x in ncpp]

    if ncpp is not None:
        n_shanks = int(probe.get("n_shanks", 1))
        return [int(ncpp)] * n_shanks

    if "kcoords" in probe:
        raw = [int(k) for k in probe["kcoords"]]
        labels = list(dict.fromkeys(raw))  # preserve order of first appearance
        return [sum(1 for k in raw if k == lab) for lab in labels]

    raise ValueError(
        "Probe JSON must define n_channels_per_shank, n_shanks, or kcoords."
    )


def _per_shank_geometry(probe: dict, shank_counts: List[int]) -> List[Tuple[list, list]]:
    """
    Return one (xc, yc) rank-order block per shank, each block's length
    matching that shank's channel count.

    - n_channels_per_shank as an int: probe["xc"]/["yc"] are a single
      shank's worth of geometry, reused (by reference) for every shank.
    - n_channels_per_shank as a list: probe["xc"]/["yc"] are the full
      probe's geometry, concatenated shank-by-shank in the same order as
      shank_counts; sliced here into one block per shank.
    """
    probe_name = probe.get("name", "unnamed")
    if "xc" not in probe or "yc" not in probe:
        raise ValueError(f"Probe '{probe_name}' is missing xc/yc geometry.")

    xc = [float(v) for v in probe["xc"]]
    yc = [float(v) for v in probe["yc"]]

    if isinstance(probe.get("n_channels_per_shank"), list):
        if len(xc) != sum(shank_counts) or len(yc) != sum(shank_counts):
            raise ValueError(
                f"Probe '{probe_name}' has {len(xc)} xc / {len(yc)} yc values, "
                f"but its shanks sum to {sum(shank_counts)} channels."
            )
        blocks = []
        start = 0
        for n in shank_counts:
            blocks.append((xc[start:start + n], yc[start:start + n]))
            start += n
        return blocks

    # Uniform case: one template, reused for every shank.
    n_shank_ch = shank_counts[0]
    if len(xc) != n_shank_ch or len(yc) != n_shank_ch:
        raise ValueError(
            f"Probe '{probe_name}' template has {len(xc)} xc and {len(yc)} yc "
            f"values, but n_channels_per_shank={n_shank_ch}."
        )
    return [(xc, yc) for _ in shank_counts]


def _resolve_probes(
    probe_names: List[str],
    data_dir: Optional[Path],
    library_dir: Optional[Path],
    layout: str,
    site_spacing: float,
    anat_grps: list,
) -> List[dict]:
    if probe_names:
        return [load_probe(name, library_dir) for name in probe_names]

    if data_dir:
        auto = Path(data_dir) / "probe.json"
        if auto.exists():
            print(f"  Probe file detected: {auto}")
            with open(auto) as f:
                return [json.load(f)]

    print(
        f"  WARNING: No probe file found. "
        f"Using fallback layout='{layout}', spacing={site_spacing} µm.\n"
        f"  For accurate results, provide a probe file (--probe <name>) "
        f"or place probe.json in the data folder."
    )
    return [_make_fallback_probe(anat_grps, layout, site_spacing)]


def _make_fallback_probe(anat_grps: list, layout: str, site_spacing: float) -> dict:
    """Synthetic probe for fallback; all groups must have equal channel counts."""
    sizes = [len(g.channels) for g in anat_grps]
    if len(set(sizes)) != 1:
        raise ValueError(
            f"Fallback layout requires all anatomical groups to have equal channel counts "
            f"(got {sizes}). Please supply a probe file."
        )
    n_ch = sizes[0]
    xc, yc = _generate_layout(n_ch, layout, site_spacing)
    return {
        "name": "fallback_" + layout,
        "n_channels_per_shank": n_ch,
        "n_shanks": len(anat_grps),
        "xc": xc,
        "yc": yc,
    }


def _generate_layout(n_ch: int, layout: str, d: float) -> Tuple[List, List]:
    """Generate (xc, yc) for one shank given a layout type and site spacing d."""
    if layout == "staggered":
        xc = [d if i % 2 == 0 else -d for i in range(n_ch)]
        yc = [i * d for i in range(n_ch)]
    elif layout == "linear":
        xc = [0.0] * n_ch
        yc = [i * d for i in range(n_ch)]
    elif layout == "columns":
        half = d / 2.0
        xc = [-half if i % 2 == 0 else half for i in range(n_ch)]
        yc = [(i // 2) * d for i in range(n_ch)]
    else:
        raise ValueError(
            f"Unknown layout: {layout!r}. Choose 'staggered', 'linear', or 'columns'."
        )
    return xc, yc


def _default_library_dir() -> Path:
    """Default probe library: Toolbox/Probes/ (two levels above this package)."""
    return Path(__file__).resolve().parent.parent.parent / "Probes"


def _probe_summary(probes: List[dict]) -> str:
    lines = []
    for p in probes:
        counts = _probe_shank_counts(p)
        n = sum(counts)
        lines.append(
            f"  {p.get('name', 'unnamed')}: "
            f"{len(counts)} shank(s) × {counts} ch = {n} ch"
        )
    return "\n".join(lines)
