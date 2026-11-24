"""Prepare the pinned PALS C++ parser and generated NARAD Python models."""

from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REVISION = "f1f69dff8a4561a781305ebc72d75cad6805a2c9"
ORIGIN = "https://github.com/pals-project/PALSParserCpp.git"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=HERE, check=True, **kwargs)


def main():
    build = HERE / ".build"
    source = build / "PALSParserCpp"
    native = build / "native"
    build.mkdir(exist_ok=True)

    if not (source / ".git").exists():
        run("git", "init", source)
    if not (source / "CMakeLists.txt").exists():
        run("git", "-C", source, "fetch", "--depth", "1", ORIGIN, REVISION)
        run("git", "-C", source, "checkout", "--detach", "FETCH_HEAD")
    revision = run("git", "-C", source, "rev-parse", "HEAD", capture_output=True, text=True)
    if revision.stdout.strip() != REVISION:
        raise RuntimeError(f"Expected PALSParserCpp at {REVISION}, found {revision.stdout.strip()}")

    run("cmake", "-S", source, "-B", native, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF", "-DPALS_BUILD_EXAMPLES=OFF",
        "-DFETCHCONTENT_UPDATES_DISCONNECTED=ON")
    run("cmake", "--build", native, "--target", "PALSParserCpp", "--parallel", "4")

    generated = HERE / "narad_models.py"
    pending = build / "narad_models.py"
    with pending.open("w") as output:
        run("gen-pydantic", HERE / "schema/narad.yaml", stdout=output)
    pending.replace(generated)


if __name__ == "__main__":
    main()
