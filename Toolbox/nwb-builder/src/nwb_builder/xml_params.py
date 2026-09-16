"""Read acquisition parameters (sampling rate, channel-to-shank map) from a
Neuroscope/NDManager .xml file."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from xml.dom import minidom

import numpy as np


@dataclass
class XmlParams:
    n_channels: int
    fs_dat: float
    fs_lfp: float
    group_to_channel: dict[int, np.ndarray]


def find_xml(session_dir: str) -> str:
    matches = glob.glob(os.path.join(session_dir, "*.xml"))
    if not matches:
        raise FileNotFoundError(f"No .xml file found in {session_dir}")
    return matches[0]


def parse_xml_params(session_dir: str) -> XmlParams:
    xml_path = find_xml(session_dir)
    doc = minidom.parse(xml_path)

    n_channels = int(
        doc.getElementsByTagName("acquisitionSystem")[0]
        .getElementsByTagName("nChannels")[0]
        .firstChild.data
    )
    fs_dat = float(
        doc.getElementsByTagName("acquisitionSystem")[0]
        .getElementsByTagName("samplingRate")[0]
        .firstChild.data
    )
    fp_nodes = doc.getElementsByTagName("fieldPotentials")
    if fp_nodes:
        fs_lfp = float(fp_nodes[0].getElementsByTagName("lfpSamplingRate")[0].firstChild.data)
    else:
        fs_lfp = fs_dat

    group_to_channel: dict[int, np.ndarray] = {}
    groups = (
        doc.getElementsByTagName("anatomicalDescription")[0]
        .getElementsByTagName("channelGroups")[0]
        .getElementsByTagName("group")
    )
    for i, group in enumerate(groups):
        group_to_channel[i] = np.array(
            [int(ch.firstChild.data) for ch in group.getElementsByTagName("channel")]
        )

    return XmlParams(n_channels=n_channels, fs_dat=fs_dat, fs_lfp=fs_lfp, group_to_channel=group_to_channel)
