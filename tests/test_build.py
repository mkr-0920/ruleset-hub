import ipaddress
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build import ROOT, domain_rule_covered, generate_config, merge, normalize, validate_config


class RulesetTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / "config/bundles.yaml").read_text(encoding="utf-8"))
        self.custom = yaml.safe_load((ROOT / "config/custom-rules.yaml").read_text(encoding="utf-8"))

    def test_exact_domain_does_not_become_suffix(self):
        self.assertEqual(normalize("# comment\nEXAMPLE.COM\n+.example.com\nexample.com\n", "domain"),
                         ["+.example.com", "example.com"])

    def test_reject_bad_or_empty_upstream(self):
        for content in ("<!doctype html>", "payload:\n - example.com", "DOMAIN,example.com", "# empty\n", "+.bad..com"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                normalize(content, "domain")
        with self.assertRaises(ValueError):
            normalize("192.168.1.7/24", "ipcidr")

    def test_ipv4_ipv6_merge_preserves_coverage(self):
        result = merge([["192.0.2.0/25", "2001:db8::/33"],
                        ["192.0.2.128/25", "2001:db8:8000::/33"]], "ipcidr")
        self.assertEqual(result, ["192.0.2.0/24", "2001:db8::/32"])
        self.assertFalse(any(ipaddress.ip_address("198.51.100.1") in ipaddress.ip_network(net)
                             for net in result if ":" not in net))

    def test_roundtrip_allows_redundancy_but_rejects_domain_broadening(self):
        self.assertTrue(domain_rule_covered("api.example.com", {"+.example.com"}))
        self.assertTrue(domain_rule_covered("+.api.example.com", {"+.example.com"}))
        self.assertFalse(domain_rule_covered("+.example.com", {"example.com"}))
        self.assertFalse(domain_rule_covered("notexample.com", {"+.example.com"}))
        self.assertFalse(domain_rule_covered("example.com", {"+.api.example.com"}))

    def test_provider_subscription_contract(self):
        validate_config(self.config, self.custom)
        providers, _ = generate_config(self.config, self.custom, "owner/ruleset-hub")
        self.assertEqual(len(providers["rule-providers"]), 15)
        self.assertEqual(providers["rule-providers"]["private"], {
            "type": "http", "behavior": "domain", "format": "mrs",
            "path": "./ruleset/private.mrs",
            "url": "https://github.com/owner/ruleset-hub/releases/download/latest/private.mrs",
            "interval": 86400, "proxy": "PROXY",
        })
        self.assertEqual(providers["rule-providers"]["directip"]["behavior"], "ipcidr")

    def test_personal_and_specialized_rules_take_priority(self):
        _, generated = generate_config(self.config, self.custom, "owner/ruleset-hub")
        rules = generated["rules"]
        onedrive_rule = f"RULE-SET,onedrive,{self.config['bundles']['onedrive']['policy']}"
        self.assertEqual(rules[:len(self.custom["rules"])], self.custom["rules"])
        for earlier, later in (
            ("DOMAIN,navidrome.010920.xyz,HOME", "DOMAIN-SUFFIX,010920.xyz,DIRECT"),
            ("RULE-SET,ai-cn,DIRECT", "RULE-SET,ai,AI"),
            ("RULE-SET,ai,AI", "RULE-SET,google,GOOGLE"),
            ("RULE-SET,netflix,NETFLIX", "RULE-SET,proxy,PROXY"),
            ("RULE-SET,netflixip,NETFLIX", "RULE-SET,proxy,PROXY"),
            ("RULE-SET,direct-services,DIRECT", "RULE-SET,proxy,PROXY"),
            ("RULE-SET,direct-services,DIRECT", onedrive_rule),
            ("RULE-SET,ai,AI", onedrive_rule),
            ("RULE-SET,tracker,DIRECT", "RULE-SET,netflixip,NETFLIX"),
            ("RULE-SET,tracker,DIRECT", "RULE-SET,proxy,PROXY"),
            (onedrive_rule, "RULE-SET,proxy,PROXY"),
            ("RULE-SET,proxy,PROXY", "RULE-SET,cn,DIRECT"),
        ):
            with self.subTest(earlier=earlier):
                self.assertLess(rules.index(earlier), rules.index(later))
        self.assertIn("RULE-SET,telegramip,TELEGRAM,no-resolve", rules)
        self.assertIn("RULE-SET,directip,DIRECT,no-resolve", rules)
        self.assertEqual(rules[-1], "MATCH,漏网之鱼")
        self.assertTrue({"applications", "networktest", "mediaip"}.isdisjoint(self.config["bundles"]))
        self.assertIn("microsoft@cn", self.config["bundles"]["direct-services"]["sources"])

    def test_no_resolve_is_only_for_ip_bundles(self):
        self.config["bundles"]["private"]["no-resolve"] = True
        with self.assertRaises(ValueError):
            validate_config(self.config, self.custom)


if __name__ == "__main__":
    unittest.main()
