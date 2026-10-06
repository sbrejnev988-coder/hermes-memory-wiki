# Совместимость: аудит 03.10.2026

**Исходная baseline** `07d54ea0831267d775a0cfb2a5b42427764f392a` (raw fingerprint `48cfe752f8e4fb7a6328adc7e094584f3f18d715f1926562b2ac65ae085ae71a`) проверена независимо. После сведения parent выполнил `merge02`: **319 passed, без failures/errors/skips**, включая все 19 тестов этого файла, 38 независимых whole-module сценариев и 6 дополнительных native RELEASE fault-injection тестов. Точная версия связана с source/JUnit receipts в `evidence/merged/`. Это не full-suite, не установленный wheel, не strict-mode или live-production acceptance.

На первой объединённой версии `merge01` 308/313 тестов прошли; 5 независимых future gates предполагали ещё не согласованное плоское поле и обязательное полное воздержание. Parent согласовал их с фактическим контрактом R01: `conflict_check = {status, scope: selected_claims}`, `conflicts` остаётся boolean; `unknown` запрещает утверждать отсутствие противоречий и требует квалификации выводов, но не исключает подтверждённые цитируемые факты. Добавлены проверки policy/citations и отсутствия приватных деталей. Исходные RED receipts и тестовый файл работника сохранены без изменений.

## Контроли и результаты

Новый [`tests/test_audit_package_contracts_20261003.py`](../tests/test_audit_package_contracts_20261003.py) содержит две явно разделённые группы:

- `-k 'not future'`: **13 passed, 6 deselected**, exit 0. Настоящие native `MemoryProvider`, `tools.registry.tool_result/tool_error`, SDK origins; полный импорт `__init__.py`, native directory loader и настоящий `importlib.metadata.EntryPoint.load()`. Регистрация hooks/активация provider не вызываются.
- `-k future`: **6 assertion failures, 13 deselected**, exit 1, без setup errors. Это ожидаемый RED baseline для F05 и пяти сценариев R01/R02, **не** проверка уже исправленного кандидата; xfail/skip не используются.
- Все **121 полных native tool dictionaries**, включая descriptions, parameters, defaults, required, constraints и порядок, сравнены с frozen cache. SHA-256 cache: `7371000445c1ead5f3a6162433d3f9d2ec6956b4c254d791b9f4a2d6b5679b12`. MCP `normalize_schema()` проверен без `load_schemas()`/регенерации cache.
- Metadata `pyproject.toml`, `plugin.yaml`, `setup.py` зафиксированы SHA-256; `PLUGIN_VERSION`/SDK/manifest остаются `1.24.0`. Никакого автоматического bump. «Info schema» здесь означает настоящие native introspection API: `get_config_schema() == []`, `identity_signature() == {}`; у baseline нет отдельного `get_info()`.
- `discovery_runtime_uninitialized=true` записан только после проверки `_conn is None`, отсутствия storage root и отсутствия новых файлов. Recall-тесты отдельно используют **реальную SQLite :memory:** и настоящий provider с reference-only SQL fixture; `initialize()`/runtime migrations не запускались.
- Owner YAML readers сохраняют graph-only Codex `gpt-6-luna-900k` отдельно от disabled conversation extraction, graph budget 700 и conversation budget 9000. Codex 9001 и OpenRouter 9000 отвергаются; файл YAML не переписывается. Это локальные settings controls, не live OAuth/HTTP inference.

Окончательные receipts/JUnit: `C:/Users/Kekl/AppData/Local/hermes/artifacts/memory-wiki-parallel-20261003T105356Z/evidence/package-contracts/contracts06-final-baseline/` и `.../contracts07-final-future-red/`. Компактный `compatibility-receipt.json` рядом содержит команды, исходные SHA-256, JUnit counts/properties и patch SHA-256. Сохранены предыдущие прогоны: `contracts01` завершился pytest INTERNALERROR (Windows devnull запрещён write fence), затем применён **только** CLI `-p no:logging`; runner/защита не изменялись.

Воспроизводимый baseline control (bash, точный SDK Python из `coordination.json`):

```bash
ROOT='C:/Users/Kekl/AppData/Local/hermes/artifacts/memory-wiki-parallel-20261003T105356Z'
SDK='C:/Users/Kekl/AppData/Local/hermes/installs/cc52de42393663ec/environments/3bc372c3d152454e8f9e117317ccfe0c/venv/Scripts/python.exe'
"$SDK" -I -B -X utf8 "$ROOT/run_isolated.py" --worker package-contracts --label contracts-baseline-repeat --package -- tests/test_audit_package_contracts_20261003.py -k 'not future' -p no:logging -o junit_family=xunit1
```

Режим `HERMES_SECURITY_STRICT=0` разрешён владельцем **лишь для изолированных процессов**, network/live profiles/nested processes запрещены runner. Это **не strict-mode acceptance**.

## Consumers, которым требуется обновление

| Изменение | Точная граница / consumer | Требование |
|---|---|---|
| F05 | [`recall_orchestrator.py:370–402`](../recall_orchestrator.py#L370) | Неподдерживаемый connection больше не доказывает актуальность non-claim evidence. Это изменение допуска evidence, само по себе не новое поле ответа; прежний source status `ok` нельзя считать гарантией final revalidation. |
| F05 mocks | [`tests/test_unified_recall.py:47–98`](../tests/test_unified_recall.py#L47); тесты `test_fuses_queries_by_stable_id_with_deterministic_rrf_and_citations`, `test_real_query_expansion_modes_and_deep_graph_acl`, `test_episode_backend_owns_acl_and_facade_rechecks_content_guard`, `test_event_channel_deduplicates_guards_and_uses_exact_host_scope`, `test_observation_channel_rechecks_scope_guard_and_emits_evidence_citation` | Перевести non-claim positives с `_Connection`/`_Provider` doubles на native provider + настоящую временную SQLite. Не возвращать bypass ради старых assertions. |
| R01/R02 | [`recall_orchestrator.py:283–298`](../recall_orchestrator.py#L283), [`:808–819`](../recall_orchestrator.py#L808), [`:1260–1283`](../recall_orchestrator.py#L1260) | Сохранить `conflicts` **bool** для старых clients; добавить `conflict_check.status: present\|absent\|unknown` с `scope=selected_claims`. `False` означает только «видимый конфликт не подтверждён», не доказанное отсутствие. При unknown `answer_policy.conflict_status` сохраняет unknown и instruction запрещает вывод «противоречий нет», требует квалифицировать выводы; `must_abstain_or_clarify` остаётся true при отсутствии допустимых citations, а не автоматически для всех unknown. Приватные IDs/SQL errors не выдаются. |
| Transport | [`__init__.py:8451–8472`](../__init__.py#L8451), [`mcp-wrapper/server.py:270`](../mcp-wrapper/server.py#L270), [`sdk.py:153–163`](../sdk.py#L153) | Сейчас проходят полные payloads/JSON; не заменять статус через `bool(status)`/`if conflicts`, не фильтровать добавленные поля. Строгие внешние response validators должны принять новый optional status; input tool schemas не меняются. |

В final RED receipts реальные native ACL показывают: missing table, visibility exception и 40 более новых foreign конфликтов перед старым видимым дают `conflicts=false`, **2 evidence**, `must_abstain=false`, status отсутствует. Обычный видимый конфликт даёт boolean true. Merge gate требует соответственно unknown/unknown/present; F05 отвергает произвольный connection.

## Граница последующей приёмки

Parent обязан повторить **весь файл без `-k`** на exact merged native package и отдельно подтвердить exhaustion/deadline → unknown из R01/R02 worker tests. Этот файл не объявляет такую бюджетную проверку выполненной. Проверять сохранение boolean consumers следует вместе с новым status/answer policy, а не одним schema count.

Wheel/ZIP не строились и не устанавливались; живые profile/config/auth/DB/registry/gateway не менялись. Entrypoint tests доказывают local import resolution, не содержимое установленного wheel. [`packaging/build_native_bundle.py:20–26`](../packaging/build_native_bundle.py#L20) читает version из working tree, но архивирует Git tree (`HEAD` по умолчанию): uncommitted merge сам по себе в архив не попадёт. Parent строит единственный объединённый artifact и проверяет его exact contents/loader paths отдельно; commit/push здесь не выполнялись.
