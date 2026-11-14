# Blowfish on PARCS-Python in AWS

Лабораторна робота №1 з дисципліни «Хмарні обчислення» (КНУ імені Тараса Шевченка,
факультет комп'ютерних наук та кібернетики).

**Тема:** паралельне шифрування алгоритмом Blowfish на платформі
[PARCS-Python](https://github.com/Hummer12007/parcs-python) у хмарі AWS.

- Blowfish реалізовано з нуля на чистому Python (режими ECB, CBC, CTR, доповнення PKCS#7).
  Код сумісний з Python 3 і Python 2.7 (вузли PARCS працюють на Python 2.7).
- Паралельна версія працює в режимі CTR: master ділить дані на частини, вирівняні на
  8-байтові блоки, і кожен воркер шифрує свою частину з власним початковим лічильником.
  Результат байт-у-байт збігається з послідовною версією.
- Експерименти проведено на 5 VM `c7i-flex.large` (1 master + 4 воркери).
  На 4 воркерах прискорення становить 3.05–3.25× (ефективність 0.76–0.81).
- Звіт: [`report/report.pdf`](report/report.pdf).

## Структура репозиторію

| Шлях | Вміст |
|---|---|
| `src/blowfish.py` | реалізація Blowfish: key schedule, мережа Фейстеля, ECB/CBC/CTR, PKCS#7, розбиття даних |
| `src/blowfish_constants.py` | P-масив і S-блоки, згенеровані з hex-цифр числа π |
| `src/jobfile.py` | формат вхідного файлу (заголовок з параметрами + дані) |
| `src/sequential.py` | послідовна версія (CLI) |
| `src/parcs_solver.py` | шаблон PARCS-розв'язувача (master + метод воркера) |
| `scripts/gen_pi_constants.py` | обчислення констант із π (формула Мечіна) |
| `scripts/build_solver.py` | збирання самодостатнього `build/solver.py` для PARCS |
| `scripts/gen_data.py` | генерація тестових вхідних файлів |
| `scripts/run_local.py` | локальний запуск розв'язувача без PARCS (воркери = процеси) |
| `scripts/run_experiments.py` | серія експериментів через HTTP API master'а → CSV |
| `scripts/analyze_results.py` | прискорення, ефективність, графіки й таблиці для звіту |
| `tests/` | тести `pytest`: вектори Шнайєра, звірка з pycryptodome, roundtrip, розв'язувач |
| `deploy/` | інструкція AWS ([`AWS_SETUP.md`](deploy/AWS_SETUP.md)), User data для VM, збір інформації про середовище |
| `results/` | сирі та агреговані результати вимірювань, лог серії, параметри середовища |
| `report/` | звіт LaTeX, графіки, таблиці, скріншоти |

## Локальний запуск

Потрібен Python 3.9+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# тести (вектори Шнайєра, pycryptodome, roundtrip, розв'язувач)
.venv/bin/pytest -q

# послідовне шифрування довільного файлу (CTR: повторний запуск розшифровує)
.venv/bin/python src/sequential.py photo.jpg --key 00112233445566778899aabbccddeeff \
    --nonce 01020304 --out photo.enc

# паралельна версія локально, без PARCS: 4 процеси-воркери
.venv/bin/python scripts/build_solver.py
.venv/bin/python scripts/gen_data.py --sizes 1 --workers 0 1 2 3 4 --repeats 2
.venv/bin/python scripts/run_local.py data/job_1mb.bin --workers 4
```

## Запуск у PARCS (AWS)

Покрокова інструкція: створення VM, security group, запуск PARCS, серія експериментів
і **видалення всіх ресурсів** — у [`deploy/AWS_SETUP.md`](deploy/AWS_SETUP.md). Коротко:

1. Запустити master і воркери (Ubuntu, x86_64) з User data із `deploy/user-data-*.sh`.
   У `user-data-worker.sh` треба підставити приватну IP master'а.
2. На master:
   ```bash
   python3 scripts/build_solver.py
   python3 scripts/gen_data.py --sizes 1 4 16 64 --workers 0 1 2 3 4 --repeats 5
   python3 scripts/run_experiments.py data/job_1mb.bin data/job_4mb.bin data/job_16mb.bin data/job_64mb.bin
   ```
   Результати зберігаються в `results/raw_results.csv` і `results/summary.csv`.
3. Вручну розв'язок теж можна запустити: у веб-інтерфейсі `http://<master>:8080` → **Add Job**
   завантажити `build/solver.py` як розв'язок і `data/job_*.bin` як вхідний файл.

## Аналіз і звіт

```bash
.venv/bin/python scripts/analyze_results.py      # results/analysis.csv, report/figures, report/tables
cd report && xelatex report.tex && xelatex report.tex
```

На Overleaf: завантажити папку `report/` як zip, у **Settings** вибрати компілятор **XeLaTeX**.

## Результати

| Розмір | T посл., с | T, 4 воркери, с | S(4) | E(4) |
|---|---|---|---|---|
| 1 МіБ | 0.429 | 0.138 | 3.11 | 0.78 |
| 4 МіБ | 1.719 | 0.529 | 3.25 | 0.81 |
| 16 МіБ | 6.846 | 2.172 | 3.15 | 0.79 |
| 64 МіБ | 27.669 | 9.074 | 3.05 | 0.76 |

Середнє з 5 повторів; повні дані — у `results/`, аналіз — у звіті.

## Автор

Уточкіна Яна Максимівна, група МІ-41, 2026.
