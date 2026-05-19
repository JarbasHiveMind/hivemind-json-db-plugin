# Changelog

## 0.0.1a1

Initial release as a standalone package. Extracted from
[`json_database/hpm.py`](https://github.com/TigreGotico/json_database/blob/dev/json_database/hpm.py).

- `JsonDB` implements `hivemind_plugin_manager.database.AbstractDB`.
- `migrate(from_version)` implements the v1->v2 schema migration:
  fold legacy `intent_blacklist`/`skill_blacklist` into `metadata`;
  purge `message_blacklist` outright.
- Schema version sentinel stored in a sibling file
  (`<name>.schema_version`) next to the JSON store.
