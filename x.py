#!/usr/bin/env python3

from collections import namedtuple
from urllib import request
import os
import subprocess
import sys

stable_rust_version = "1.77.0"
supported_rust_versions = [stable_rust_version, "nightly"]
rustup_version = "1.27.0"

DebianArch = namedtuple("DebianArch", ["bashbrew", "dpkg", "qemu", "rust"])

debian_arches = [
    DebianArch("amd64", "amd64", "linux/amd64", "x86_64-unknown-linux-gnu"),
    DebianArch("arm32v7", "armhf", "linux/arm/v7", "armv7-unknown-linux-gnueabihf"),
    DebianArch("arm64v8", "arm64", "linux/arm64", "aarch64-unknown-linux-gnu"),
    DebianArch("i386", "i386", "linux/386", "i686-unknown-linux-gnu"),
]

debian_non_buster_arches = [
    DebianArch("ppc64le", "ppc64el", "linux/ppc64le", "powerpc64le-unknown-linux-gnu"),
]

debian_variants = [
    "buster",
    "bullseye",
    "bookworm",
]

default_debian_variant = "bookworm"

AlpineArch = namedtuple("AlpineArch", ["bashbrew", "apk", "qemu", "rust"])

alpine_arches = [
    AlpineArch("amd64", "x86_64", "linux/amd64", "x86_64-unknown-linux-musl"),
    AlpineArch("arm64v8", "aarch64", "linux/arm64", "aarch64-unknown-linux-musl"),
]

alpine_versions = [
    "3.18",
    "3.19",
]

default_alpine_version = "3.19"

def rustup_hash(arch):
    url = f"https://static.rust-lang.org/rustup/archive/{rustup_version}/{arch}/rustup-init.sha256"
    with request.urlopen(url) as f:
        return f.read().decode('utf-8').split()[0]

def read_file(file):
    with open(file, "r") as f:
        return f.read()

def write_file(file, contents):
    dir = os.path.dirname(file)
    if dir and not os.path.exists(dir):
        os.makedirs(dir)
    with open(file, "w") as f:
        f.write(contents)

def update_debian():
    arch_case = 'dpkgArch="$(dpkg --print-architecture)"; \\\n'
    arch_case += '    case "${dpkgArch##*-}" in \\\n'
    for arch in debian_arches:
        hash = rustup_hash(arch.rust)
        arch_case += f"        {arch.dpkg}) rustArch='{arch.rust}'; rustupSha256='{hash}' ;; \\\n"

    end = '        *) echo >&2 "unsupported architecture: ${dpkgArch}"; exit 1 ;; \\\n'
    end += '    esac'

    template = read_file("Dockerfile-debian.template")
    slim_template = read_file("Dockerfile-slim.template")

    for variant in debian_variants:
        case = arch_case
        if variant != "buster":
            for arch in debian_non_buster_arches:
                hash = rustup_hash(arch.rust)
                case += f"        {arch.dpkg}) rustArch='{arch.rust}'; rustupSha256='{hash}' ;; \\\n"

        case += end

        for rust_version in supported_rust_versions:
            rendered = template \
                .replace("%%RUST-VERSION%%", rust_version) \
                .replace("%%RUSTUP-VERSION%%", rustup_version) \
                .replace("%%DEBIAN-SUITE%%", variant) \
                .replace("%%ARCH-CASE%%", case)
            write_file(f"{rust_version}/{variant}/Dockerfile", rendered)

            rendered = slim_template \
                .replace("%%RUST-VERSION%%", rust_version) \
                .replace("%%RUSTUP-VERSION%%", rustup_version) \
                .replace("%%DEBIAN-SUITE%%", variant) \
                .replace("%%ARCH-CASE%%", case)
            write_file(f"{rust_version}/{variant}/slim/Dockerfile", rendered)

def update_alpine():
    arch_case = 'apkArch="$(apk --print-arch)"; \\\n'
    arch_case += '    case "$apkArch" in \\\n'
    for arch in alpine_arches:
        hash = rustup_hash(arch.rust)
        arch_case += f"        {arch.apk}) rustArch='{arch.rust}'; rustupSha256='{hash}' ;; \\\n"
    arch_case += '        *) echo >&2 "unsupported architecture: $apkArch"; exit 1 ;; \\\n'
    arch_case += '    esac'

    template = read_file("Dockerfile-alpine.template")

    for version in alpine_versions:
        for rust_version in supported_rust_versions:
            rendered = template \
                .replace("%%RUST-VERSION%%", rust_version) \
                .replace("%%RUSTUP-VERSION%%", rustup_version) \
                .replace("%%TAG%%", version) \
                .replace("%%ARCH-CASE%%", arch_case)
            write_file(f"{rust_version}/alpine{version}/Dockerfile", rendered)

def update_ci():
    file = ".github/workflows/ci.yml"
    config = read_file(file)

    marker = "#RUST_VERSION\n"
    split = config.split(marker)
    rendered = split[0] + marker + f"      RUST_VERSION: {stable_rust_version}\n" + marker + split[2]

    versions = ""
    for variant in debian_variants:
        versions += f"          - name: {variant}\n"
        versions += f"            variant: {variant}\n"
        versions += f"          - name: slim-{variant}\n"
        versions += f"            variant: {variant}/slim\n"

    for version in alpine_versions:
        versions += f"          - name: alpine{version}\n"
        versions += f"            variant: alpine{version}\n"

    marker = "#VERSIONS\n"
    split = rendered.split(marker)
    rendered = split[0] + marker + versions + marker + split[2]
    write_file(file, rendered)

def update_nightly_ci():
    file = ".github/workflows/nightly.yml"
    config = read_file(file)


    versions = ""
    for variant in debian_variants:
        platforms = []
        for arch in debian_arches:
            platforms.append(f"{arch.qemu}")
        if variant != "buster":
            for arch in debian_non_buster_arches:
                platforms.append(f"{arch.qemu}")
        platforms = ",".join(platforms)

        tags = [f"nightly-{variant}"]
        if variant == default_debian_variant:
            tags.append("nightly")

        versions += f"          - name: {variant}\n"
        versions += f"            context: nightly/{variant}\n"
        versions += f"            platforms: {platforms}\n"
        versions += f"            tags: |\n"
        for tag in tags:
            versions += f"              {tag}\n"

        versions += f"          - name: slim-{variant}\n"
        versions += f"            context: nightly/{variant}/slim\n"
        versions += f"            platforms: {platforms}\n"
        versions += f"            tags: |\n"
        for tag in tags:
            versions += f"              {tag}-slim\n"

    for version in alpine_versions:
        platforms = []
        for arch in alpine_arches:
            platforms.append(f"{arch.qemu}")
        platforms = ",".join(platforms)

        tags = [f"nightly-alpine{version}"]
        if version == default_alpine_version:
            tags.append("nightly-alpine")

        versions += f"          - name: alpine{version}\n"
        versions += f"            context: nightly/alpine{version}\n"
        versions += f"            platforms: {platforms}\n"
        versions += f"            tags: |\n"
        for tag in tags:
            versions += f"              {tag}\n"

    marker = "#VERSIONS\n"
    split = config.split(marker)
    rendered = split[0] + marker + versions + marker + split[2]
    write_file(file, rendered)

def file_commit(file):
    return subprocess.run(
            ["git", "log", "-1", "--format=%H", "HEAD", "--", file],
            capture_output = True) \
        .stdout \
        .decode('utf-8') \
        .strip()

def version_tags():
    parts = stable_rust_version.split(".")
    tags = []
    for i in range(len(parts)):
        tags.append(".".join(parts[:i + 1]))
    return tags

def single_library(tags, architectures, dir):
    return f"""
Tags: {", ".join(tags)}
Architectures: {", ".join(architectures)}
GitCommit: {file_commit(os.path.join(dir, "Dockerfile"))}
Directory: {dir}
"""

def generate_stackbrew_library():
    commit = file_commit("x.py")

    library = f"""\
# this file is generated via https://github.com/rust-lang/docker-rust/blob/{commit}/x.py

Maintainers: Steven Fackler <sfackler@gmail.com> (@sfackler),
             Scott Schafer <schaferjscott@gmail.com> (@Muscraft)
GitRepo: https://github.com/rust-lang/docker-rust.git
"""

    for variant in debian_variants:
        tags = []
        for version_tag in version_tags():
            tags.append(f"{version_tag}-{variant}")
        tags.append(variant)
        if variant == default_debian_variant:
            for version_tag in version_tags():
                tags.append(version_tag)
            tags.append("latest")

        arches = debian_arches[:]
        if variant != "buster":
            arches += debian_non_buster_arches

        library += single_library(
                tags,
                map(lambda a: a.bashbrew, arches),
                os.path.join(stable_rust_version, variant))

        tags = []
        for version_tag in version_tags():
            tags.append(f"{version_tag}-slim-{variant}")
        tags.append(f"slim-{variant}")
        if variant == default_debian_variant:
            for version_tag in version_tags():
                tags.append(f"{version_tag}-slim")
            tags.append("slim")

        library += single_library(
                tags,
                map(lambda a: a.bashbrew, arches),
                os.path.join(stable_rust_version, variant, "slim"))

    for version in alpine_versions:
        tags = []
        for version_tag in version_tags():
            tags.append(f"{version_tag}-alpine{version}")
        tags.append(f"alpine{version}")
        if version == default_alpine_version:
            for version_tag in version_tags():
                tags.append(f"{version_tag}-alpine")
            tags.append("alpine")

        library += single_library(
            tags,
            map(lambda a: a.bashbrew, alpine_arches),
            os.path.join(stable_rust_version, f"alpine{version}"))

    print(library)

def usage():
    print(f"Usage: {sys.argv[0]} update|generate-stackbrew-library")
    sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        usage()

    task = sys.argv[1]
    if task == "update":
        update_debian()
        update_alpine()
        update_ci()
        update_nightly_ci()
    elif task == "generate-stackbrew-library":
        generate_stackbrew_library()
    else:
        usage()
