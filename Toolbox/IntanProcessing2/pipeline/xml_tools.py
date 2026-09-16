"""
xml_tools.py
============
Ports of LoadXml.m and UpdateXml_SpkGrps.m from the MATLAB pipeline.

The Neuroscope/NDManager XML format is described at:
  https://neurosuite.sourceforge.net/formats.html

Typical structure:
  <parameters>
    <generalInfo>...</generalInfo>
    <acquisitionSystem>
      <nBits>16</nBits>
      <nChannels>64</nChannels>
      <samplingRate>20000</samplingRate>
      <voltageRange>20</voltageRange>
      <amplification>1000</amplification>
      <offset>0</offset>
    </acquisitionSystem>
    <fieldPotentials>
      <lfpSamplingRate>1250</lfpSamplingRate>
    </fieldPotentials>
    <anatomicalDescription>
      <channelGroups>
        <group>
          <channel skip="0">0</channel>
          ...
        </group>
      </channelGroups>
    </anatomicalDescription>
    <spikeDetection>
      <channelGroups>
        <group>
          <channels>
            <channel>0</channel>
            ...
          </channels>
          <nSamples>32</nSamples>
          <peakSampleIndex>16</peakSampleIndex>
          <nFeatures>3</nFeatures>
        </group>
      </channelGroups>
    </spikeDetection>
  </parameters>
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ChannelGroup:
    channels: List[int] = field(default_factory=list)
    skip:     List[int] = field(default_factory=list)   # anatomical groups only
    n_samples:         Optional[int] = None
    peak_sample_index: Optional[int] = None
    n_features:        Optional[int] = None


@dataclass
class XmlParams:
    """Python equivalent of the 'xml' struct returned by LoadXml.m"""
    filename:        str = ""
    date:            str = ""
    n_bits:          int = 16
    n_channels:      int = 0
    sample_rate:     int = 20_000
    voltage_range:   float = 20.0
    amplification:   float = 1000.0
    offset:          int = 0
    lfp_sample_rate: int = 1_250
    hi_pass_freq:    Optional[float] = None
    anat_grps:       List[ChannelGroup] = field(default_factory=list)
    spk_grps:        List[ChannelGroup] = field(default_factory=list)


def load_xml(path: Path | str) -> XmlParams:
    """
    Parse a Neuroscope .xml parameter file and return an XmlParams object.
    Equivalent to LoadXml.m.
    """
    path = Path(path)
    if path.suffix.lower() != ".xml":
        path = path.with_suffix(".xml")

    tree = ET.parse(path)
    root = tree.getroot()          # <parameters>

    p = XmlParams(filename=str(path))

    for child in root:
        tag = child.tag.lower()

        if tag == "generalinfo":
            date_el = child.find("date")
            if date_el is not None:
                p.date = date_el.text or ""

        elif tag == "acquisitionsystem":
            _get_int(child, "nBits",          lambda v: setattr(p, "n_bits", v))
            _get_int(child, "nChannels",      lambda v: setattr(p, "n_channels", v))
            _get_int(child, "samplingRate",   lambda v: setattr(p, "sample_rate", v))
            _get_float(child, "voltageRange", lambda v: setattr(p, "voltage_range", v))
            _get_float(child, "amplification",lambda v: setattr(p, "amplification", v))
            _get_int(child, "offset",         lambda v: setattr(p, "offset", v))

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
                        skip_val = ch_el.get("skip", "0")
                        grp.skip.append(int(skip_val))
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


def generate_xml(
    dst_path: "Path | str",
    n_channels: int,
    sample_rate: float,
    groups: "List[List[int]]",
    lfp_sample_rate: int = 1_250,
    voltage_range: float = 20.0,
    amplification: float = 1_000.0,
) -> None:
    """
    Write a minimal Neuroscope-compatible XML parameter file.

    Parameters
    ----------
    dst_path       : output .xml path
    n_channels     : total number of amplifier channels
    sample_rate    : recording sample rate in Hz
    groups         : list of lists of 0-based channel indices (one list per shank/port)
    """
    dst_path = Path(dst_path)

    root = ET.Element("parameters", version="1.0")

    acq = ET.SubElement(root, "acquisitionSystem")
    for tag, val in [
        ("nBits", "16"),
        ("nChannels", str(n_channels)),
        ("samplingRate", str(int(round(sample_rate)))),
        ("voltageRange", str(voltage_range)),
        ("amplification", str(amplification)),
        ("offset", "0"),
    ]:
        el = ET.SubElement(acq, tag)
        el.text = val

    fp = ET.SubElement(root, "fieldPotentials")
    ET.SubElement(fp, "lfpSamplingRate").text = str(lfp_sample_rate)

    anat = ET.SubElement(root, "anatomicalDescription")
    cgrps = ET.SubElement(anat, "channelGroups")
    for grp_channels in groups:
        grp_el = ET.SubElement(cgrps, "group")
        for ch in grp_channels:
            ch_el = ET.SubElement(grp_el, "channel")
            ch_el.set("skip", "0")
            ch_el.text = str(ch)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst_path), encoding="unicode", xml_declaration=False)
    print(f"      XML generated from info.rhd: {dst_path.name}  "
          f"({n_channels} ch, {int(round(sample_rate))} Hz, {len(groups)} group(s))")


def update_xml_spk_grps(
    path: Path | str,
    n_samples: int = 32,
    peak_sample_index: int = 16,
    n_features: int = 3,
) -> None:
    """
    Update (or add) nSamples, peakSampleIndex, nFeatures in every
    <spikeDetection><channelGroups><group> block.

    Equivalent to UpdateXml_SpkGrps.m.
    Writes the result back to the same file.
    """
    path = Path(path)
    if path.suffix.lower() != ".xml":
        path = path.with_suffix(".xml")

    tree = ET.parse(path)
    root = tree.getroot()

    # Find or create <spikeDetection>
    spk_det = None
    for child in root:
        if child.tag.lower() == "spikedetection":
            spk_det = child
            break

    if spk_det is None:
        return   # no spike groups defined – nothing to update

    grps_el = spk_det.find("channelGroups")
    if grps_el is None:
        return

    for grp_el in grps_el.findall("group"):
        _set_or_create(grp_el, "nSamples",         str(n_samples))
        _set_or_create(grp_el, "peakSampleIndex",  str(peak_sample_index))
        _set_or_create(grp_el, "nFeatures",        str(n_features))

    # Write with indentation (Python 3.9+)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _set_or_create(parent: ET.Element, tag: str, value: str) -> None:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value
