"""
Download and unzip the Household Pulse Survey public-use files (weeks 22–34, 2021).

Two ways to get the raw data into data/raw/:
  1. Automatic:  download_pulse()  fetches each week's CSV zip from Census.
  2. Manual:     download the zips yourself from
                 https://www.census.gov/programs-surveys/household-pulse-survey/data/datasets.2021.html
                 and place them (still zipped) in data/raw/.
Either way, then run unzip_pulse(), which extracts each zip into
data/raw/HPS_Week<NN>_PUF_CSV/.
"""
import os
import zipfile
from pathlib import Path

import requests

try:
    from tqdm import tqdm
except ImportError:          # progress bars are optional
    def tqdm(iterable=None, **kwargs):
        return _NoBar(iterable)

    class _NoBar:
        def __init__(self, iterable=None):
            self.iterable = iterable
        def __iter__(self):
            return iter(self.iterable or [])
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def update(self, n):
            pass

ROOT = Path(__file__).resolve().parents[1]      # repo root
RAW_DIR = ROOT / "data" / "raw"
WEEKS = list(range(22, 35))                     # 22..34 -> 13 waves

# Census file-naming pattern for 2021 weekly releases.
BASE_URL = "https://www2.census.gov/programs-surveys/demo/datasets/hhp/2021/wk{w}/HPS_Week{w}_PUF_CSV.zip"


def zip_name(week):
    return f"HPS_Week{week}_PUF_CSV.zip"


def pulse_file_list(weeks=WEEKS):
    """List of {'url', 'filename'} dicts for the given weeks, in the format get_raw() expects."""
    return [{"url": BASE_URL.format(w=w), "filename": zip_name(w)} for w in weeks]


def get_raw(file_list, destination_directory, overwrite=False, timeout=60):
    """
    Downloads a list of files to a destination directory with progress bars.

    Args:
        file_list (list): dicts with 'url' and 'filename'.
        destination_directory (str or Path): created if it does not exist.
        overwrite (bool): re-download files that already exist.
        timeout (int): seconds to wait for the server before giving up.

    Returns:
        list of filenames that failed to download.
    """
    destination_directory = Path(destination_directory)
    destination_directory.mkdir(parents=True, exist_ok=True)
    failed = []

    for file_info in tqdm(file_list, desc="Overall Download Progress"):
        url, filename = file_info["url"], file_info["filename"]
        local_filepath = destination_directory / filename
        if local_filepath.exists() and not overwrite:
            print(f"Already present, skipping: {filename}")
            continue

        partial = local_filepath.with_suffix(local_filepath.suffix + ".part")
        try:
            with requests.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                with open(partial, "wb") as f, tqdm(total=total_size, unit="B", unit_scale=True,
                                                     desc=f"Downloading {filename}", leave=False) as pbar:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            os.replace(partial, local_filepath)    # only a complete download gets the real name
            print(f"Successfully downloaded: {filename}")
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {filename}: {e}")
            failed.append(filename)
        except Exception as e:
            print(f"An unexpected error occurred for {filename}: {e}")
            failed.append(filename)
        finally:
            if partial.exists():
                partial.unlink()
    return failed


def download_pulse(weeks=WEEKS, raw_dir=RAW_DIR, overwrite=False):
    """Download each week's CSV zip into raw_dir. Returns the list of failures."""
    failed = get_raw(pulse_file_list(weeks), raw_dir, overwrite=overwrite)
    if failed:
        print("\nSome downloads failed. Download these manually from the Census 2021 Pulse page "
              f"and place the zips in {raw_dir}:\n  " + "\n  ".join(failed))
    return failed


def _safe_extract(zf, target):
    """Extract a zip, refusing any member that would land outside target."""
    target = Path(target).resolve()
    for member in zf.namelist():
        dest = (target / member).resolve()
        if target != dest and target not in dest.parents:
            raise ValueError(f"Unsafe path in zip: {member}")
    zf.extractall(target)


def unzip_pulse(weeks=WEEKS, raw_dir=RAW_DIR, overwrite=False):
    """
    Extract data/raw/HPS_Week<NN>_PUF_CSV.zip into data/raw/HPS_Week<NN>_PUF_CSV/.
    Skips weeks already extracted. Returns a dict week -> status.
    """
    raw_dir = Path(raw_dir)
    status = {}
    for w in weeks:
        zpath = raw_dir / zip_name(w)
        out = raw_dir / zpath.stem
        if out.exists() and any(out.rglob(f"pulse2021_puf_{w}.csv")) and not overwrite:
            status[w] = "already extracted"
            continue
        if not zpath.exists():
            status[w] = "MISSING ZIP"
            continue
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, out)
        status[w] = "extracted"
    for w, s in status.items():
        print(f"week {w}: {s}")
    return status


def find_week_files(week, raw_dir=RAW_DIR):
    """
    Locate a week's main and replicate-weight CSVs anywhere under raw_dir
    (handles zips that unpack into a nested folder).
    """
    raw_dir = Path(raw_dir)
    puf = next(raw_dir.rglob(f"pulse2021_puf_{week}.csv"), None)
    rep = next(raw_dir.rglob(f"pulse2021_repwgt_puf_{week}.csv"), None)
    if puf is None or rep is None:
        raise FileNotFoundError(f"Week {week}: could not find the main and/or replicate-weight CSV "
                                f"under {raw_dir}. Run unzip_pulse() first.")
    return puf, rep


if __name__ == "__main__":
    download_pulse()
    unzip_pulse()
