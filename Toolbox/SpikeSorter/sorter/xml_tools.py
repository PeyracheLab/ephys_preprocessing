"""
xml_tools.py
============
Minimal XML loader for Neuroscope/NDManager parameter files.
Reads channel counts, sample rate, and spike group definitions needed for
spike sorting and Neurosuite export.

This is a self-contained copy of the relevant subset from IntanProcessing2.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ChannelGroup:
    channels:          List[int] = field(default_factory=list)
    skip:              List[int] = field(default_factory=list)
    n_samples:         Optional[int] = None
    peak_sample_index: Optional[int] = None
    n_features:        Optional[int] = None


@dataclass
class XmlParams:
    filename:        str   = ""
    date:            str   = ""
    n_bits:          int   = 16
    n_channels:      int   = 0
    sample_rate:     int   = 20_000
    voltage_range:   float = 20.0
    amplification:   float = 1000.0
    offset:          int   = 0
    lfp_sample_rate: int   = 1_250
    hi_pass_freq:    Optional[float] = None
    anat_grps:       List[ChannelGroup] = field(default_factory=list)
    spk_grps:        List[ChannelGroup] = field(default_factory=list)


def load_xml(path: "Path | str") -> XmlParams:
    """Parse a Neuroscope .xml parameter file and return an XmlParams object."""
    path = Path(path)
    if path.suffix.lower() != ".xml":
        path = path.with_suffix(".xml")

    tree = ET.parse(path)
    root = tree.getroot()

    p = XmlParams(filename=str(path))

    for child in root:
        tag = child.tag.lower()

        if tag == "generalinfo":
            el = child.find("date")
            if el is not None:
                p.date = el.text or ""

        elif tag == "acquisitionsystem":
            _get_int(child,   "nBits",         lambda v: setattr(p, "n_bits", v))
            _get_int(child,   "nChannels",     lambda v: setattr(p, "n_channels", v))
            _get_int(child,   "samplingRate",  lambda v: setattr(p, "sample_rate", v))
            _get_float(child, "voltageRange",  lambda v: setattr(p, "voltage_range", v))
            _get_float(child, "amplification", lambda v: setattr(p, "amplification", v))
            _get_int(child,   "offset",        lambda v: setattr(p, "offset", v))

        elif tag == "fieldpotentials":
            _get_int(child, "lfpSamplingRate",
                     lambda v: setattr(p, "lfp_sample_rate", v))

        elif tag == "anatomicaldescription":
            grps_el = child.find("channelGroups")
            if grps_el is not None:
                for grp_el in grps_el.findall("group"):
                    grp = ChannelGroup()
                    for ch_el in grp_el.findall("channel"):
                        grp.channels.append(int(ch_el.text or 0))
                        grp.skip.append(int(ch_el.get("skip", "0")))
                    p.anat_grps.append(grp)

        elif tag == "spikedetection":
            grps_el = child.find("channelGroups")
            if grps_el is not None:
                for grp_el in grps_el.findall("group"):
                    grp = ChannelGroup()
                    ch_grp = grp_el.find("channels")
                    if ch_grp is not None:
                        for ch_el in ch_grp.findall("channel"):
                            grp.channels.append(int(ch_el.text or 0))
                    _get_int(grp_el, "nSamples",
                             lambda v: setattr(grp, "n_samples", v))
                    _get_int(grp_el, "peakSampleIndex",
                             lambda v: setattr(grp, "peak_sample_index", v))
                    _get_int(grp_el, "nFeatures",
                             lambda v: setattr(grp, "n_features", v))
                    p.spk_grps.append(grp)

    return p


def ensure_spk_grps(
    path:             "Path | str",
    n_samples:        int = 32,
    peak_sample_index: int = 16,
    n_features:       int = 3,
) -> bool:
    """
    Ensure the XML has a complete <spikeDetection> block with waveform parameters.

    Two cases are handled:
      1. <spikeDetection> is empty or absent → build spike groups from
         <anatomicalDescription>, including only channels with skip="0".
      2. <spikeDetection> groups exist but are missing nSamples / peakSampleIndex
         / nFeatures → add/update those values.

    Writes the updated XML back to the same file.
    Returns True if the file was modified, False if it was already complete.
    """
    path = Path(path)
    if path.suffix.lower() != ".xml":
        path = path.with_suffix(".xml")

    tree = ET.parse(path)
    root = tree.getroot()

    # ── Locate or create <spikeDetection> ────────────────────────────────────
    spk_det = None
    for child in root:
        if child.tag.lower() == "spikedetection":
            spk_det = child
            break
    if spk_det is None:
        spk_det = ET.SubElement(root, "spikeDetection")

    grps_el = spk_det.find("channelGroups")

    # ── If no spike groups exist, build from anatomical groups ────────────────
    if grps_el is None or len(grps_el.findall("group")) == 0:
        # Find anatomical groups
        anat_grps_el = None
        for child in root:
            if child.tag.lower() == "anatomicaldescription":
                anat_grps_el = child.find("channelGroups")
                break

        if anat_grps_el is None:
            raise ValueError(
                "XML has no <anatomicalDescription> — cannot build spike groups."
            )

        if grps_el is None:
            grps_el = ET.SubElement(spk_det, "channelGroups")

        for anat_grp in anat_grps_el.findall("group"):
            active_channels = [
                ch_el for ch_el in anat_grp.findall("channel")
                if ch_el.get("skip", "0") == "0"
            ]
            if not active_channels:
                continue

            grp_el = ET.SubElement(grps_el, "group")
            ch_container = ET.SubElement(grp_el, "channels")
            for ch_el in active_channels:
                new_ch = ET.SubElement(ch_container, "channel")
                new_ch.text = ch_el.text
            # waveform parameters added below

        print(f"  XML: built <spikeDetection> from {len(grps_el.findall('group'))} "
              f"anatomical groups")
        modified = True
    else:
        modified = False

    # ── Add/update nSamples, peakSampleIndex, nFeatures in every group ────────
    for grp_el in grps_el.findall("group"):
        changed  = _set_if_missing(grp_el, "nSamples",        str(n_samples))
        changed |= _set_if_missing(grp_el, "peakSampleIndex", str(peak_sample_index))
        changed |= _set_if_missing(grp_el, "nFeatures",       str(n_features))
        modified |= changed

    if modified:
        ET.indent(tree, space="  ")
        tree.write(path, encoding="unicode", xml_declaration=False)
        print(f"  XML updated: {path.name}  "
              f"(nSamples={n_samples}, peakSampleIndex={peak_sample_index}, "
              f"nFeatures={n_features})")

    return modified


# ── Helpers ────────────────────────────────────────────────────────────────────

def _set_if_missing(parent: ET.Element, tag: str, value: str) -> bool:
    """Set an element's text only if the element is absent or empty. Returns True if changed."""
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
        el.text = value
        return True
    if not el.text:
        el.text = value
        return True
    return False



def _get_int(parent: ET.Element, tag: str, setter) -> None:
    el = parent.find(tag)
    if el is not None and el.text:
        try:
            setter(int(el.text))
        except ValueError:
            pass


def _get_float(parent: ET.Element, tag: str, setter) -> None:
    el = parent.find(tag)
    if el is not None and el.text:
        try:
            setter(float(el.text))
        except ValueError:
            pass
