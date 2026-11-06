from services.integrity import (config_hash, diff_configs, normalize_value,
                                parse_config)
from services.risk import assess_change, assess_changes


def test_parser_preserves_spaces_and_quotes():
    text = (
        '/system note\n'
        'set note=Core edge router - baseline v1\n'
        '/ip firewall filter\n'
        'add chain=input action=accept comment="allow mgmt from NOC"\n'
        'add chain=input action=drop comment="route=default allow"\n'
    )
    entries = parse_config(text)
    assert entries['system note:note'].value == 'Core edge router - baseline v1'
    assert entries['ip firewall filter:comment=allow mgmt from NOC.comment'].value == (
        'allow mgmt from NOC')
    assert entries['ip firewall filter:comment=route=default allow.comment'].value == (
        'route=default allow')


def test_parser_flat_values_with_spaces_and_crlf():
    text = 'description = Edge router with two uplinks\r\nowner: NOC Team Jakarta\r\n'
    entries = parse_config(text)
    assert entries['global:description'].value == 'Edge router with two uplinks'
    assert entries['global:owner'].value == 'NOC Team Jakarta'


def test_disabled_key_is_context_aware():
    assert normalize_value('yes', 'disabled') == 'disabled'
    assert normalize_value('no', 'disabled') == 'enabled'
    assert normalize_value('enabled', 'disabled') == 'disabled'
    assert normalize_value('disabled', 'disabled') == 'enabled'
    assert normalize_value('yes', 'ssh.disabled') == 'disabled'
    assert normalize_value('no', 'ssh.disabled') == 'enabled'


def test_enabled_key_is_context_aware():
    assert normalize_value('yes', 'enabled') == 'enabled'
    assert normalize_value('no', 'enabled') == 'disabled'
    assert normalize_value('true', 'allow-remote-requests') == 'enabled'
    assert normalize_value('false', 'allow-remote-requests') == 'disabled'
    assert normalize_value('yes', 'name') == 'yes'


def test_sha256_is_semantic_and_stable():
    first = 'a=1\nb=two words\n# comment\n'
    second = 'b=two words\r\na=1\r\n'
    assert config_hash(first) == config_hash(second)
    assert config_hash(first) != config_hash('a=1\nb=two words changed\n')
    assert config_hash('/ip service\nset ssh disabled=yes') == config_hash(
        '/ip service\nset ssh disabled=true')


def test_semantic_diff_detects_modified_value():
    old = '/system note\nset note=Core edge router - baseline v1\n'
    new = '/system note\nset note=Core edge router - maintenance window NOC 2026-11-03\n'
    changes, _, _ = diff_configs(old, new)
    assert len(changes) == 1
    change = changes[0]
    assert change.change_type == 'MODIFIED'
    assert change.param == 'note'
    assert change.old_value == 'Core edge router - baseline v1'
    assert change.new_value == 'Core edge router - maintenance window NOC 2026-11-03'


def test_normal_change_is_low_risk():
    old = '/system note\nset note=Core edge router - baseline v1\n'
    new = '/system note\nset note=Core edge router - maintenance window NOC 2026-11-03\n'
    changes, _, _ = diff_configs(old, new)
    assessments, highest, _note = assess_changes(changes)
    assert highest == 'LOW'
    assert assessments[0]['rule_id'] == 'DESCRIPTION_CHANGED'


def test_firewall_disable_is_high_risk():
    old = '/ip firewall filter\nset enabled=enabled\n'
    new = '/ip firewall filter\nset enabled=disabled\n'
    changes, _, _ = diff_configs(old, new)
    assert len(changes) == 1
    result = assess_change(changes[0])
    assert result['risk_level'] == 'HIGH'
    assert result['rule_id'] == 'FIREWALL_DISABLED'


def test_ssh_enable_is_high_risk():
    old = '/ip service\nset ssh disabled=yes port=22\n'
    new = '/ip service\nset ssh disabled=no port=22\n'
    changes, _, _ = diff_configs(old, new)
    assert len(changes) == 1
    assert changes[0].old_value == 'disabled'
    assert changes[0].new_value == 'enabled'
    result = assess_change(changes[0])
    assert result['risk_level'] == 'HIGH'
    assert result['rule_id'] == 'SERVICE_SSH_ENABLED'
