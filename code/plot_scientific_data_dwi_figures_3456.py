#!/usr/bin/env python3
"""Scientific Data Figures 3-6: Motion, SNR/CNR, Eddy-analog QC, GSLD vs RESOLVE."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path("/lustre07/scratch/alexrees")
PUB = ROOT / "derivatives/dmriqc/publication"
PUB.mkdir(parents=True, exist_ok=True)
MET = ROOT / "derivatives/dmriqc/qc_metrics/dwi_motion_snr_qc.tsv"
SIGNAL = ROOT / "reports/dwi_qc/Signal_QC.tsv"
PROTO = ROOT / "reports/dwi_qc/Protocol_Consistency_per_scan.tsv"
INV = ROOT / "derivatives/dmriqc/audit/dmriqc_sequence_inventory.tsv"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10,
    "axes.labelsize": 9, "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 140, "savefig.dpi": 300, "savefig.bbox": "tight",
})
COL = {"GSLD": "#1f4e79", "RESOLVE": "#548235", "ses-01": "#1f4e79",
       "ses-02": "#c45911", "accent": "#c45911"}


def num(x):
    try:
        return float(x) if x not in (None, "") else np.nan
    except Exception:
        return np.nan


def read_tsv(path: Path):
    return list(csv.DictReader(open(path), delimiter="\t")) if path.exists() else []


def save(fig, stem: Path):
    fig.savefig(stem.with_suffix(".png"))
    fig.savefig(stem.with_suffix(".pdf"))
    plt.close(fig)
    print("wrote", stem.with_suffix(".png"))


def violin(ax, data_list, labels, colors, ylabel, title):
    data_list = [np.asarray(d, float)[np.isfinite(np.asarray(d, float))] for d in data_list]
    keep = [(d, l, c) for d, l, c in zip(data_list, labels, colors) if len(d) > 0]
    if not keep:
        ax.text(0.5, 0.5, "No data", ha="center", transform=ax.transAxes)
        ax.set_title(title, loc="left", fontweight="bold")
        return
    data_list, labels, colors = zip(*keep)
    parts = ax.violinplot(list(data_list), showmeans=False, showmedians=True, showextrema=False)
    for i, pc in enumerate(parts["bodies"]):
        pc.set_facecolor(colors[i]); pc.set_alpha(0.75); pc.set_edgecolor("white")
    if "cmedians" in parts:
        parts["cmedians"].set_color("#222"); parts["cmedians"].set_linewidth(1.2)
    rng = np.random.default_rng(0)
    for i, d in enumerate(data_list, start=1):
        dd = rng.choice(d, min(400, len(d)), replace=False) if len(d) else d
        ax.scatter(i + rng.uniform(-0.08, 0.08, len(dd)), dd, s=6, alpha=0.25,
                   c=[colors[i - 1]], edgecolors="none", zorder=3)
    ax.set_xticks(range(1, len(labels) + 1)); ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel); ax.set_title(title, loc="left", fontweight="bold")
    ymin, ymax = ax.get_ylim()
    for i, d in enumerate(data_list, start=1):
        ax.text(i, ymax, f"n={len(d)}", ha="center", va="bottom", fontsize=7)


def strip(ax, data_list, labels, colors, ylabel, title, rng=None):
    """Strip / jitter point-cloud panel (same annotations as violin)."""
    rng = rng or np.random.default_rng(0)
    data_list = [np.asarray(d, float)[np.isfinite(np.asarray(d, float))] for d in data_list]
    keep = [(d, l, c) for d, l, c in zip(data_list, labels, colors) if len(d) > 0]
    if not keep:
        ax.text(0.5, 0.5, "No data", ha="center", transform=ax.transAxes)
        ax.set_title(title, loc="left", fontweight="bold")
        return
    data_list, labels, colors = zip(*keep)
    for i, (d, c) in enumerate(zip(data_list, colors), start=1):
        x = i + rng.uniform(-0.18, 0.18, size=len(d))
        ax.scatter(
            x, d, s=14, alpha=0.40, c=[c], edgecolors="none", zorder=2, rasterized=True
        )
        med = float(np.median(d))
        ax.hlines(med, i - 0.22, i + 0.22, colors="#222", linewidths=2.0, zorder=3)
    tick_labels = []
    for lab, d in zip(labels, data_list):
        med = float(np.median(d))
        tick_labels.append(f"{lab}\nmed={med:.3g}\nn={len(d)}")
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(tick_labels)
    ax.set_xlim(0.45, len(labels) + 0.55)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")


def load_metrics():
    met = read_tsv(MET)
    sig = {r["scan_id"]: r for r in read_tsv(SIGNAL) if r.get("scan_id")}
    proto = {r["scan_id"]: r for r in read_tsv(PROTO) if r.get("scan_id")}
    inv_map = {r["bids_basename"]: r for r in read_tsv(INV)}
    rows = []
    if met and any(r.get("status") == "OK" for r in met):
        for r in met:
            if r.get("status") != "OK":
                continue
            sid = r["scan_id"]
            fam = r.get("sequence_family") or ""
            seq = "GSLD" if fam.startswith("GSLD") else ("RESOLVE" if fam.startswith("RESOLVE") else fam)
            p = proto.get(sid, {})
            rows.append({
                "scan_id": sid, "subject": r.get("subject"), "session": r.get("session"),
                "run": r.get("run"), "sequence": seq, "family": fam,
                "trans_mean": num(r.get("trans_rms_mean_mm")),
                "rot_mean": num(r.get("rot_mean_deg")),
                "slice_out_mean": num(r.get("slice_outliers_mean")),
                "pct_vol_outlier": num(r.get("pct_volumes_with_slice_outlier")),
                "snr": num(r.get("b0_SNR")), "cnr": num(r.get("CNR")),
                "vox_x": num(p.get("voxel_size_x")), "vox_y": num(p.get("voxel_size_y")),
                "vox_z": num(p.get("voxel_size_z")), "TE": num(p.get("TE_s")),
                "ESP_proxy": num(p.get("TotalReadoutTime")),
                "n_dirs": num(p.get("n_diffusion_directions")),
            })
        return rows, "computed"
    for sid, s in sig.items():
        if s.get("b0_SNR") in ("", None):
            continue
        p = proto.get(sid, {})
        pid = s.get("protocol_id") or p.get("protocol_id") or ""
        if pid in ("Protocol A", "Protocol C", "Protocol D", "Protocol E", "Protocol F"):
            seq = "GSLD"
        elif pid == "Protocol B":
            seq = "RESOLVE"
        else:
            fam = inv_map.get(sid, {}).get("sequence_family", "")
            seq = "GSLD" if fam.startswith("GSLD") else ("RESOLVE" if fam.startswith("RESOLVE") else "OTHER")
        rows.append({
            "scan_id": sid, "subject": s.get("subject"), "session": s.get("session"),
            "run": s.get("run"), "sequence": seq, "family": seq,
            "trans_mean": np.nan, "rot_mean": np.nan, "slice_out_mean": np.nan,
            "pct_vol_outlier": np.nan, "snr": num(s.get("b0_SNR")), "cnr": num(s.get("CNR")),
            "vox_x": num(p.get("voxel_size_x")), "vox_y": num(p.get("voxel_size_y")),
            "vox_z": num(p.get("voxel_size_z")), "TE": num(p.get("TE_s")),
            "ESP_proxy": num(p.get("TotalReadoutTime")),
            "n_dirs": num(p.get("n_diffusion_directions")),
        })
    return rows, "fallback_signal_qc"


def figure3_motion(rows):
    gsld = [r for r in rows if r["sequence"] == "GSLD"]
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.6))
    panels = [
        (axes[0], "trans_mean", "Mean translation RMS (mm)\nacross b0 volumes", "A. Translation"),
        (axes[1], "rot_mean", "Mean in-plane orientation change (deg)", "B. Rotation"),
        (axes[2], "slice_out_mean", "Mean outlier slices / volume", "C. Slice outliers"),
    ]
    for ax, key, xlab, title in panels:
        plotted = False
        for ses, col in [("ses-01", COL["ses-01"]), ("ses-02", COL["ses-02"])]:
            d = np.asarray([r[key] for r in gsld if r["session"] == ses], float)
            d = d[np.isfinite(d)]
            if not len(d):
                continue
            plotted = True
            ax.hist(d, bins=25, alpha=0.55, color=col, label=f"{ses} (n={len(d)})", edgecolor="white")
        ax.set_xlabel(xlab); ax.set_ylabel("Scans"); ax.set_title(title, loc="left", fontweight="bold")
        if plotted:
            ax.legend(frameon=False, fontsize=8)
        else:
            ax.text(0.5, 0.5, "Motion metrics pending\n(compute job)", ha="center", va="center",
                    transform=ax.transAxes, color="#666")
    n = sum(1 for r in gsld if np.isfinite(r["trans_mean"]))
    fig.suptitle(f"Figure 3 — Motion QC on GSLD acquisitions (n={n})", fontsize=11, fontweight="bold", y=1.03)
    fig.tight_layout(); save(fig, PUB / "Figure3_Motion_GSLD")


def _run_key(run) -> str:
    s = str(run or "").strip().lower().replace("run-", "")
    s = s.lstrip("0") or "0"
    return s


def figure4_snr_cnr(rows):
    """Strip panels split by GSLD run-01 / run-02 to avoid mixed bimodal clouds."""
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 7.0))
    rng = np.random.default_rng(0)

    def vals(seq=None, run=None, ses=None, key="snr"):
        out = []
        for r in rows:
            if seq is not None and r["sequence"] != seq:
                continue
            if run is not None and _run_key(r.get("run")) != str(run):
                continue
            if ses is not None and r.get("session") != ses:
                continue
            v = r[key]
            if np.isfinite(v):
                out.append(v)
        return out

    # A/B: separate GSLD runs so each column is unimodal
    strip(
        axes[0, 0],
        [vals("GSLD", "1"), vals("GSLD", "2"), vals("RESOLVE")],
        ["GSLD run-01", "GSLD run-02", "RESOLVE"],
        [COL["GSLD"], "#5b8db8", COL["RESOLVE"]],
        "b0 SNR (median / MAD noise)",
        "A. SNR by sequence / GSLD run",
        rng=rng,
    )
    strip(
        axes[0, 1],
        [vals("GSLD", "1", key="cnr"), vals("GSLD", "2", key="cnr"), vals("RESOLVE", key="cnr")],
        ["GSLD run-01", "GSLD run-02", "RESOLVE"],
        [COL["GSLD"], "#5b8db8", COL["RESOLVE"]],
        "CNR (|b0−DW| / MAD noise)",
        "B. CNR by sequence / GSLD run",
        rng=rng,
    )
    # C: session × run so sessions are not bimodal mixtures
    strip(
        axes[1, 0],
        [
            vals("GSLD", "1", "ses-01"),
            vals("GSLD", "2", "ses-01"),
            vals("GSLD", "1", "ses-02"),
            vals("GSLD", "2", "ses-02"),
        ],
        ["ses-01\nrun-01", "ses-01\nrun-02", "ses-02\nrun-01", "ses-02\nrun-02"],
        [COL["ses-01"], "#5b8db8", COL["ses-02"], "#e09a5c"],
        "b0 SNR",
        "C. GSLD SNR by session × run",
        rng=rng,
    )
    # D: subject means on run-01 only (avoids averaging high+collapsed SNR)
    ax = axes[1, 1]
    by_sub = defaultdict(list)
    for r in rows:
        if r["sequence"] == "GSLD" and _run_key(r.get("run")) == "1" and np.isfinite(r["snr"]):
            by_sub[r["subject"]].append(r["snr"])
    sub_mean = np.array([np.mean(v) for v in by_sub.values()])
    if len(sub_mean):
        ax.hist(sub_mean, bins=20, color=COL["GSLD"], edgecolor="white")
        cv = 100 * np.std(sub_mean) / (np.mean(sub_mean) + 1e-6)
        ax.axvline(np.median(sub_mean), color=COL["accent"], lw=1.5,
                   label=f"median={np.median(sub_mean):.1f}")
        ax.set_xlabel("Subject-mean b0 SNR (GSLD run-01)")
        ax.set_ylabel("Subjects")
        ax.set_title(f"D. Between-subject homogeneity (CV={cv:.1f}%)",
                     loc="left", fontweight="bold")
        ax.legend(frameon=False, fontsize=8)
    else:
        ax.text(0.5, 0.5, "No SNR", ha="center", transform=ax.transAxes)
    fig.suptitle("Figure 4 — SNR / CNR (data homogeneity)", fontsize=11, fontweight="bold", y=1.01)
    fig.tight_layout()
    save(fig, PUB / "Figure4_SNR_CNR")


def figure5_eddy_analog(rows):
    gsld = [r for r in rows if r["sequence"] == "GSLD"]
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.6))
    panels = [
        (axes[0], [r["slice_out_mean"] for r in gsld], "Mean outlier slices / volume", "A. Outlier slices"),
        (axes[1], [r["pct_vol_outlier"] for r in gsld], "% volumes with ≥1 slice outlier", "B. Volumes affected"),
        (axes[2], [r["trans_mean"] for r in gsld], "Mean motion (translation RMS, mm)", "C. Mean motion"),
    ]
    for ax, data, xlab, title in panels:
        d = np.asarray(data, float); d = d[np.isfinite(d)]
        if not len(d):
            ax.text(0.5, 0.5, "Pending motion compute", ha="center", transform=ax.transAxes, color="#666")
            ax.set_title(title, loc="left", fontweight="bold"); continue
        ax.hist(d, bins=24, color=COL["GSLD"], edgecolor="white")
        ax.axvline(np.median(d), color=COL["accent"], lw=1.5, label=f"median={np.median(d):.2g}")
        ax.set_xlabel(xlab); ax.set_ylabel("Scans"); ax.set_title(title, loc="left", fontweight="bold")
        ax.legend(frameon=False, fontsize=8)
    n = sum(1 for r in gsld if np.isfinite(r["slice_out_mean"]))
    fig.suptitle(f"Figure 5 — Volume QC (eddy-analogous; raw DWI, n={n} GSLD)",
                 fontsize=11, fontweight="bold", y=1.03)
    fig.tight_layout(); save(fig, PUB / "Figure5_EddyAnalog_QC")


def figure6_gsld_vs_resolve(rows):
    fig, axes = plt.subplots(2, 3, figsize=(11.2, 6.8))
    g = [r for r in rows if r["sequence"] == "GSLD"]
    r = [r for r in rows if r["sequence"] == "RESOLVE"]
    violin(axes[0, 0], [[x["snr"] for x in g], [x["snr"] for x in r]],
           ["GSLD", "RESOLVE"], [COL["GSLD"], COL["RESOLVE"]], "b0 SNR", "A. SNR")
    violin(axes[0, 1], [[x["cnr"] for x in g], [x["cnr"] for x in r]],
           ["GSLD", "RESOLVE"], [COL["GSLD"], COL["RESOLVE"]], "CNR", "B. CNR")
    ax = axes[0, 2]
    gv = [np.mean([x["vox_x"], x["vox_y"]]) for x in g if np.isfinite(x["vox_x"])]
    rv = [np.mean([x["vox_x"], x["vox_y"]]) for x in r if np.isfinite(x["vox_x"])]
    gz = [x["vox_z"] for x in g if np.isfinite(x["vox_z"])]
    rz = [x["vox_z"] for x in r if np.isfinite(x["vox_z"])]
    x = np.arange(2)
    gmed = [np.median(gv) if gv else np.nan, np.median(gz) if gz else np.nan]
    rmed = [np.median(rv) if rv else np.nan, np.median(rz) if rz else np.nan]
    ax.bar(x - 0.18, gmed, 0.35, color=COL["GSLD"], label="GSLD")
    ax.bar(x + 0.18, rmed, 0.35, color=COL["RESOLVE"], label="RESOLVE")
    ax.set_xticks(x); ax.set_xticklabels(["In-plane", "Slice"])
    ax.set_ylabel("Voxel size (mm)"); ax.set_title("C. Voxel size", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    violin(axes[1, 0],
           [[x["TE"] * 1000 for x in g if np.isfinite(x["TE"])],
            [x["TE"] * 1000 for x in r if np.isfinite(x["TE"])]],
           ["GSLD", "RESOLVE"], [COL["GSLD"], COL["RESOLVE"]], "TE (ms)", "D. Echo time")
    violin(axes[1, 1],
           [[x["ESP_proxy"] * 1000 for x in g if np.isfinite(x["ESP_proxy"])],
            [x["ESP_proxy"] * 1000 for x in r if np.isfinite(x["ESP_proxy"])]],
           ["GSLD", "RESOLVE"], [COL["GSLD"], COL["RESOLVE"]],
           "Total readout time (ms)", "E. Susceptibility / echo-train proxy")
    ax = axes[1, 2]
    gd = [x["n_dirs"] for x in g if np.isfinite(x["n_dirs"])]
    rd = [x["n_dirs"] for x in r if np.isfinite(x["n_dirs"])]
    ax.bar([0], [np.median(gd) if gd else 0], color=COL["GSLD"], width=0.5,
           label=f"GSLD med={np.median(gd) if gd else 0:.0f}")
    ax.bar([1], [np.median(rd) if rd else 0], color=COL["RESOLVE"], width=0.5,
           label=f"RESOLVE med={np.median(rd) if rd else 0:.0f}")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["GSLD", "RESOLVE"])
    ax.set_ylabel("Diffusion directions")
    ax.set_title("F. Angular sampling", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=7)
    fig.suptitle("Figure 6 — GSLD vs RESOLVE: complementary diffusion acquisitions",
                 fontsize=11, fontweight="bold", y=1.01)
    fig.tight_layout(); save(fig, PUB / "Figure6_GSLD_vs_RESOLVE")


def write_caption(source, rows):
    n_g = sum(1 for r in rows if r["sequence"] == "GSLD")
    n_r = sum(1 for r in rows if r["sequence"] == "RESOLVE")
    n_mot = sum(1 for r in rows if r["sequence"] == "GSLD" and np.isfinite(r["trans_mean"]))
    (PUB / "Figure3to6_CAPTIONS.md").write_text(f"""# Figures 3–6 captions (Scientific Data)

Source: `{source}` · GSLD n={n_g} · RESOLVE n={n_r} · GSLD with motion={n_mot}

## Figure 3 — Motion (GSLD)
Raw GSLD b0 inter-volume motion (no FSL eddy): translation COM RMS (mm),
in-plane principal-axis rotation (deg), slice intensity outliers (|z|>3.5).

## Figure 4 — SNR / CNR
Homogeneity across sequences and sessions (MAD-noise SNR/CNR).

## Figure 5 — Eddy-analogous volume QC
Raw-DWI proxies (eddy derivatives not in this release).

## Figure 6 — GSLD vs RESOLVE
Complementary research multi-shell vs clinical RESOLVE.
""")


def main():
    rows, source = load_metrics()
    print(f"loaded {len(rows)} rows from {source}")
    figure3_motion(rows)
    figure4_snr_cnr(rows)
    figure5_eddy_analog(rows)
    figure6_gsld_vs_resolve(rows)
    write_caption(source, rows)
    out = PUB / "Figure3to6_summary_stats.tsv"
    with open(out, "w", newline="") as f:
        fields = ["sequence", "n", "snr_median", "cnr_median", "trans_median_mm",
                  "rot_median_deg", "slice_out_median", "TE_median_ms", "readout_median_ms"]
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t"); w.writeheader()
        for seq in ("GSLD", "RESOLVE"):
            rs = [r for r in rows if r["sequence"] == seq]
            def med(key, scale=1.0):
                v = np.array([r[key] * scale for r in rs if np.isfinite(r[key])], float)
                return float(np.median(v)) if len(v) else ""
            w.writerow({"sequence": seq, "n": len(rs), "snr_median": med("snr"),
                        "cnr_median": med("cnr"), "trans_median_mm": med("trans_mean"),
                        "rot_median_deg": med("rot_mean"), "slice_out_median": med("slice_out_mean"),
                        "TE_median_ms": med("TE", 1000), "readout_median_ms": med("ESP_proxy", 1000)})
    print("wrote", out); print("DONE")


if __name__ == "__main__":
    main()
