# CLAUDE.md

Этот файл содержит инструкции для Claude Code (claude.ai/code) при работе с данным репозиторием.

## Сборка

```bash
make                  # Собрать vock + mode/kcov.so (по умолчанию clang)
make CC=gcc           # Собрать с GCC вместо clang
make clean            # Удалить артефакты сборки
```

## Запуск тестов

Функциональный тест запускается через `selftest/run.py` посредством собранного бинаря:

```bash
./vock selftest --on vng-kvm --kernel-src ~/linux   # Собрать KCOV-ядро, прогнать сбор покрытия
./vock selftest --on vng-tcg --kernel-src ~/linux   # То же без KVM (CI)
```

Юнит-тесты генератора отчёта (Python):

```bash
python3 -m pytest tests/
```

CI (`.github/workflows/ci.yml`) собирает vock и запускает selftest при каждом push. Линтер не настроен.

## Архитектура

**vock** — инструмент на C для сбора покрытия ядра Linux через KCOV и генерации HTML-отчёта.

### Поток данных

1. **Запуск цели** — `vock <cmd>` форкает целевую программу с `LD_PRELOAD=mode/kcov.so`
2. **Сбор покрытия** — `mode/kcov.c` (через KCOV: local + remote) захватывает адреса инструкций ядра → `kerncov.log`
3. **Отчётность** — `output.py` + `report/*.py` разрешают адреса через addr2line → `coverage.html`

### Структура модулей

| Директория | Назначение |
|---|---|
| `vock.c` | Точка входа: разбор CLI, запуск цели под KCOV, вызов генератора отчёта |
| `mode/kcov.c` | Shared lib (LD_PRELOAD): включает KCOV local+remote в целевом процессе, пишет `kerncov.log` |
| `output.py` | CLI генератора отчёта: читает `kerncov.log`, оркестрирует разрешение и вывод |
| `report/` | Python-генерация отчёта: `resolve.py` (addr2line), `elf.py` (инструментированные строки из DWARF), `kaslr.py` (компенсация KASLR), `html.py` (HTML) |
| `selftest/run.py` | Функциональный тест: сборка KCOV-ядра в virtme-ng и проверка сбора покрытия |
| `tests/` | Юнит-тесты Python для генератора отчёта (`pytest`) |

### Ключевые архитектурные решения

- **KCOV local + remote**: `mode/kcov.c` включает локальное покрытие (пути syscall текущей задачи) и удалённое (softirq/workqueue), затем объединяет в `kerncov.log`
- **Разрешение адресов**: covered-PC из `kerncov.log` разрешаются в `file:line` через `addr2line` по `vmlinux`; инструментированные (но не покрытые) строки извлекаются из DWARF `.debug_line`
- **Компенсация KASLR**: смещение определяется автоматически по `vmlinux` и вычитается из адресов перед разрешением
- **Требует root**: KCOV доступен через `/sys/kernel/debug/kcov`, поэтому `vock` требует привилегий root
