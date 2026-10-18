# Memory Wiki 1.24.6

## Состав

Публикационный кандидат продолжает принятый source checkpoint
`67c26fede27c1ec9c1a1316ee86e416e0ff5ec5a` после публичного main
`7319ca04476476fd54bada7882a17aeb53fbfe31`.

- Original owner/read-set удерживается до внешней отправки, публикации
  Qdrant и owning COMMIT; поздний отзыв не легализуется новым snapshot.
- Graph/background extraction сохраняет source/session identity, queued intent
  и retry при временно недоступных settings/guard, без ложного ACK.
- Recovery сохраняет erasure namespace и атомарность bootstrap; обязательная
  редактировка секретов отказывает до записи при недоступной зависимости.
- Версии plugin manifest, project, uv self-record, runtime и Python SDK —
  **1.24.6**. MCP API v1, 121 tool schema, SDK API 1.0 и версии схем данных
  не повышаются без изменения соответствующего контракта.

Это упаковочный выпуск существующих исправлений, не новые roadmap-функции.
Модели, credentials, пользовательские stores/settings и Core/SDK/PM не меняются.
Исторические receipts, gold и предыдущие release notes сохранены.

## Проверка и границы

Канонические проверки: `packaging/verify_release.py --tag v1.24.6`,
`packaging/generate_tool_schemas.py --check`, MCP compatibility, applicable
offline regressions, wheel/RECORD/source correspondence и native ZIP/Git blobs.
Сборка выполняется вне frozen checkout с `SOURCE_DATE_EPOCH` и offline build
dependencies. Native ZIP требует immutable tree-ish; не архивируйте dirty HEAD.

Local SOURCE и metadata/build результаты не заменяют полный native bootstrap,
production strict import, cross-platform Python 3.11–3.14, services или loaded
fleet. Официальные test/release workflows сохраняют minimum core
`NousResearch/hermes-agent@5307e93252ac655cd13fadbd561c0995142138c6`.
Manual synthetic workflow с прежним d526 PIN — отдельный исторический gate,
не обязательный новый запуск этого выпуска и не источник нового allowance.
Успехи предыдущих версий не переносятся на новые bytes как свежий FULL PASS.

## Публикация и установка

1. Оператор проверяет clean candidate commit/tree, реальные результаты packet
   и независимое review. Публикует exact source и tag `v1.24.6` без force push.
   GitHub source, tag, Release и asset SHA читаются обратно раздельно.
   Стандартный tag workflow публикует GitHub Release, **не PyPI**.
2. До native install разрешаются текущие профили и shared-PM layout, scanner,
   liveness и code rollback. При нескольких копиях одного distribution name
   одна остаётся buildable; metadata-only secondary source подготавливается
   отдельно до PM admission, а не патчится после неудачной установки.
3. Используется штатный exact-PIN plugin installer; следуйте актуальным
   native parser/PM guards. Native ZIP и wheel — артефакты выпуска, не повод
   обходить scanner/trust или копировать файлы поверх активного профиля.
4. Strict runtime требует подлинный совместимый `hermes_trust_core` и остальные
   обязательные companion dependencies по действующему loader. Не выключайте
   strict mode и не копируйте live lib/credentials ради зелёной проверки.
5. Проверяются установленный PIN/payload, enabled status и сохранность собственных
   настроек каждого профиля. Code-only install не открывает live store ради smoke.
   Перезапуск и последующая проверка loaded code/public lifecycle — отдельный
   owner-run этап. Code rollback не является восстановлением пользовательских данных.

Этот документ не утверждает, что push, GitHub Release, установка или reload уже
выполнены. Их завершение подтверждается отдельным exact-target readback.