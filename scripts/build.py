"""Merge a single upstream snapshot, compile MRS, validate and prepare Release assets."""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

from install_mihomo import ROOT, install


def download(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "ruleset-hub", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=60) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed: {url}")


def normalize(content: str, behavior: str) -> list[str]:
    rules = set()
    for number, raw in enumerate(content.splitlines(), 1):
        rule = raw.strip().lstrip("\ufeff")
        if not rule or rule.startswith("#"):
            continue
        if behavior == "domain":
            rule = rule.lower()
            domain = rule[2:] if rule.startswith("+.") else rule
            # Preserve exact vs suffix matching. Do not broaden exact rules.
            if not re.fullmatch(r"[a-z0-9_*.-]+", domain) or any(
                not label for label in domain.split(".")
            ):
                raise ValueError(f"Invalid domain rule on line {number}: {raw!r}")
        elif behavior == "ipcidr":
            rule = str(ipaddress.ip_network(rule, strict=True))
        else:
            raise ValueError(f"Unsupported behavior: {behavior}")
        rules.add(rule)
    if not rules:
        raise ValueError("Source contains no rules")
    return sorted(rules)


def merge(parts: list[list[str]], behavior: str) -> list[str]:
    merged = sorted({rule for part in parts for rule in part})
    if behavior == "ipcidr":
        networks = [ipaddress.ip_network(rule) for rule in merged]
        merged = [str(network) for version in (4, 6) for network in ipaddress.collapse_addresses(
            network for network in networks if network.version == version
        )]
    return merged


def dump_yaml(path: Path, content: dict) -> None:
    path.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")


def domain_rule_covered(rule: str, candidates: set[str]) -> bool:
    if rule in candidates:
        return True
    labels = (rule[2:] if rule.startswith("+.") else rule).split(".")
    return any("+." + ".".join(labels[index:]) in candidates for index in range(len(labels)))


def verify_mrs(mihomo: Path, path: Path, behavior: str, entries: list[str]) -> int:
    decoded_path = path.with_suffix(".decoded")
    subprocess.run([
        str(mihomo), "convert-ruleset", behavior, "mrs", str(path), str(decoded_path),
    ], check=True)
    decoded = normalize(decoded_path.read_text(encoding="utf-8"), behavior)
    original_set, decoded_set = set(entries), set(decoded)
    if behavior == "domain":
        # Mihomo may remove an exact rule already covered by a suffix rule.
        equal = all(domain_rule_covered(rule, decoded_set) for rule in original_set) and all(
            domain_rule_covered(rule, original_set) for rule in decoded_set
        )
    else:
        equal = original_set == decoded_set
    if not equal:
        raise ValueError(f"MRS round-trip changed rule coverage: {path.name}")
    decoded_path.unlink()
    return len(decoded)


def validate_config(config: dict, custom: dict) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["upstream"]["repository"]):
        raise ValueError("Invalid upstream repository")
    if not config.get("bundles") or not isinstance(config.get("fallback"), str):
        raise ValueError("bundles and fallback are required")
    for name, bundle in config["bundles"].items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise ValueError(f"Invalid bundle name: {name}")
        if bundle["behavior"] not in {"domain", "ipcidr"}:
            raise ValueError(f"Unsupported behavior for {name}")
        if not isinstance(bundle["policy"], str) or not bundle["policy"]:
            raise ValueError(f"Missing policy for {name}")
        if not isinstance(bundle.get("sources"), list) or not bundle["sources"]:
            raise ValueError(f"No sources for {name}")
        if any(not isinstance(source, str) or not re.fullmatch(r"[a-z0-9@!_.-]+", source)
               for source in bundle["sources"]):
            raise ValueError(f"Invalid source for {name}")
        if "no-resolve" in bundle and (
            bundle["behavior"] != "ipcidr" or not isinstance(bundle["no-resolve"], bool)
        ):
            raise ValueError(f"no-resolve must be boolean and only used with ipcidr: {name}")
    if not isinstance(custom.get("rules"), list) or any(
        not isinstance(rule, str) for rule in custom["rules"]
    ):
        raise ValueError("custom-rules.yaml must contain a rules list")


def generate_config(config: dict, custom: dict, repository: str) -> tuple[dict, dict]:
    providers = {}
    rules = list(custom["rules"])
    for name, bundle in config["bundles"].items():
        providers[name] = {
            "type": "http",
            "behavior": bundle["behavior"],
            "format": "mrs",
            "path": f"./ruleset/{name}.mrs",
            "url": f"https://github.com/{repository}/releases/download/latest/{name}.mrs",
            "interval": 86400,
            "proxy": "PROXY",
        }
        rule = f"RULE-SET,{name},{bundle['policy']}"
        if bundle.get("no-resolve"):
            rule += ",no-resolve"
        rules.append(rule)
    rules.append(f"MATCH,{config['fallback']}")
    return {"rule-providers": providers}, {"rules": rules}


def check_mihomo(mihomo: Path, stage: Path, providers: dict, rules: dict) -> None:
    # Check exactly the generated HTTP/MRS providers, backed by local files so
    # validation never needs the not-yet-published Release or actual proxy nodes.
    check_home = stage / "check"
    check_home.mkdir()
    (check_home / "ruleset").mkdir()
    for name in providers["rule-providers"]:
        shutil.copy2(stage / f"{name}.mrs", check_home / "ruleset" / f"{name}.mrs")
    policies = {rule.split(",")[-1] if not rule.endswith(",no-resolve")
                else rule.split(",")[-2] for rule in rules["rules"]}
    policies.add("PROXY")
    check_config = {
        "mode": "rule",
        "log-level": "warning",
        "proxy-groups": [
            {"name": policy, "type": "select", "proxies": ["DIRECT"]}
            for policy in sorted(policies - {"DIRECT", "REJECT"})
        ],
        **providers,
        **rules,
    }
    config_path = check_home / "config.yaml"
    dump_yaml(config_path, check_config)
    subprocess.run([str(mihomo), "-t", "-d", str(check_home), "-f", str(config_path)], check=True)
    # Also verify the equivalent file-provider configuration. MRS payloads are
    # checked independently by decoding and comparing their coverage.
    for name, provider in check_config["rule-providers"].items():
        provider["type"] = "file"
        for field in ("url", "interval", "proxy"):
            provider.pop(field, None)
    dump_yaml(config_path, check_config)
    subprocess.run([str(mihomo), "-t", "-d", str(check_home), "-f", str(config_path)], check=True)
    shutil.rmtree(check_home)


def build(repository: str, upstream_ref: str | None, mihomo: Path) -> None:
    config = yaml.safe_load((ROOT / "config" / "bundles.yaml").read_text(encoding="utf-8"))
    custom = yaml.safe_load((ROOT / "config" / "custom-rules.yaml").read_text(encoding="utf-8"))
    validate_config(config, custom)
    upstream = config["upstream"]["repository"]
    ref = upstream_ref or config["upstream"]["ref"]
    if re.fullmatch(r"[a-f0-9]{40}", ref):
        sha = ref
    else:
        commit = json.loads(download(
            f"https://api.github.com/repos/{upstream}/commits/{quote(ref, safe='')}",
            os.environ.get("GITHUB_TOKEN"),
        ))
        sha = commit["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Upstream returned an invalid commit SHA")
    version = subprocess.check_output([str(mihomo), "-v"], text=True, encoding="utf-8").strip()
    print(f"Upstream snapshot: {upstream}@{sha}", flush=True)
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "build_commit": os.environ.get("GITHUB_SHA"),
        "mihomo": version,
        "upstream": {"repository": upstream, "ref": ref, "sha": sha},
        "bundles": {},
    }
    cached_sources = {}
    with tempfile.TemporaryDirectory(prefix=".ruleset-build-", dir=ROOT) as temporary:
        stage = Path(temporary) / "assets"
        stage.mkdir()
        for name, bundle in config["bundles"].items():
            behavior = bundle["behavior"]
            category = "geosite" if behavior == "domain" else "geoip"
            parts, sources = [], []
            for source in bundle["sources"]:
                path = f"geo/{category}/{source}.list"
                if path not in cached_sources:
                    url = f"https://raw.githubusercontent.com/{upstream}/{sha}/{quote(path, safe='/')}"
                    print(f"Downloading {path}", flush=True)
                    raw = download(url)
                    entries = normalize(raw.decode("utf-8-sig"), behavior)
                    cached_sources[path] = (entries, {
                        "path": path, "url": url, "count": len(entries),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    })
                entries, metadata = cached_sources[path]
                parts.append(entries)
                sources.append(metadata)
            entries = merge(parts, behavior)
            text_path = stage / f"{name}.list"
            text_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            mrs_path = stage / f"{name}.mrs"
            subprocess.run([
                str(mihomo), "convert-ruleset", behavior, "text", str(text_path), str(mrs_path),
            ], check=True)
            if not mrs_path.is_file() or mrs_path.stat().st_size <= 4:
                raise ValueError(f"Missing or empty MRS: {name}")
            compiled_count = verify_mrs(mihomo, mrs_path, behavior, entries)
            manifest["bundles"][name] = {
                "behavior": behavior, "policy": bundle["policy"],
                "count": len(entries), "compiled_count": compiled_count, "sources": sources,
            }
            print(f"Built {name}.mrs: {len(entries)} merged rules", flush=True)
        providers, rules = generate_config(config, custom, repository)
        dump_yaml(stage / "rule-providers.yaml", providers)
        dump_yaml(stage / "rules.yaml", rules)
        dump_yaml(stage / "mihomo.yaml", {**providers, **rules})
        check_mihomo(mihomo, stage, providers, rules)
        # Record checksums of all payloads. The manifest itself is covered by SHA256SUMS.
        manifest["files"] = {
            path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(stage.iterdir())
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        checksums = "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(stage.iterdir())
        )
        (stage / "SHA256SUMS").write_text(checksums, encoding="utf-8")
        output = ROOT / "dist"
        # Only replace the managed directory after the complete build passes.
        if output.is_symlink() or output.resolve() != ROOT / "dist":
            raise ValueError("Refusing to replace a redirected dist directory")
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    print(f"Ready: {len(manifest['bundles'])} MRS files in {output}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"), help="Your GitHub owner/repo")
    parser.add_argument("--upstream-ref", help="Override upstream branch or pin a 40-character commit SHA")
    parser.add_argument("--mihomo", type=Path, help="Use an existing Mihomo executable")
    args = parser.parse_args()
    if not args.repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("--repository OWNER/REPO is required outside GitHub Actions")
    mihomo = args.mihomo.resolve() if args.mihomo else install()
    build(args.repository, args.upstream_ref, mihomo)


if __name__ == "__main__":
    main()
