# Custom BIDS Naming Rules

Optional lab-defined rules that refine BIDS entities **after** sequence classification
and **before** the conversion plan is shown / executed.

## Priority

1. User-defined rules (`SmartNamingRulesEngine`)
2. Existing sequence classifier / BIDS entity resolver
3. Default BIDS naming helpers (`build_bids_target`)

With no rules configured, behaviour is unchanged.

## Safety

Rules never modify DICOM files. They only change the in-memory `BIDSConversionPlan`
and inventory / preview columns.

## Configuration

Rules are stored as JSON in the per-user state directory:

- Linux: `~/.local/state/NeuroPipeline_DICOM_Converter/naming_rules.json`
- Windows: `%LOCALAPPDATA%\NeuroPipeline_DICOM_Converter\naming_rules.json`

Edit via **Settings → Naming Rules**, or import/export JSON.

### Example

```json
{
  "rules": [
    {
      "name": "REST Siemens AP rule",
      "enabled": true,
      "priority": 10,
      "conditions": {
        "ProtocolName_contains": "REST_AP"
      },
      "actions": {
        "task": "rest",
        "datatype": "func",
        "suffix": "bold"
      }
    }
  ]
}
```

Condition keys: `FieldName_contains|equals|startswith|endswith|regex`  
Fields: `ProtocolName`, `SeriesDescription`, `SequenceName`, `Modality`, …

Lower **priority** number wins when multiple rules match.

## Where rules appear

- BIDS Preview → **Naming Rule** column
- Inventory.xlsx → **Naming Rule Applied**
- Conversion plan JSON (`naming_rule_applied`)

## Validation

Settings → Naming Rules → **Validate** checks duplicate priorities, invalid entities,
invalid characters, and conflicting condition/action sets.
