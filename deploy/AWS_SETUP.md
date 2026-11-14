# Розгортання PARCS-Python в AWS і запуск експериментів

Інструкція для акаунта на **Free plan** (кредити AWS), регіон **eu-north-1 (Stockholm)**,
квота On-Demand Standard = 16 vCPU.

Позначення:
- `W` — кількість VM-воркерів (рекомендовано **6**, мінімум 4; 1 master + 6 workers = 14 vCPU ≤ 16);
- `MASTER_PUBLIC_IP` — публічна IPv4 master-VM (для SSH і веб-інтерфейсу);
- `MASTER_PRIVATE_IP` — приватна IPv4 master-VM (172.31.x.x, для зв'язку всередині AWS);
- **[Mac]** — команду виконувати в Terminal на своєму Mac, **[master]** — у SSH-сесії на master-VM.

## Архітектура

```
                 Інтернет (тільки з твоєї IP: SSH 22, веб-інтерфейс 8080)
                                   |
   +------------------------- VPC за замовчуванням, eu-north-1 ---------------------------+
   |   Security group "parcs-sg": усі з'єднання дозволені лише між VM цієї ж групи        |
   |                                                                                     |
   |   parcs-master (c7i-flex.large)        parcs-worker x W (c7i-flex.large)            |
   |   docker: hummer12007/parcs-node  <--> docker: hummer12007/parcs-node               |
   |   PARCS master :8080, solver.solve()   PARCS worker, Pyro4 RPC (encrypt_chunk)      |
   +-------------------------------------------------------------------------------------+
```

---

## Частина A. Створення інфраструктури

### A1. SSH-ключ
1. Консоль AWS → переконайся, що вгорі праворуч вибрано **Europe (Stockholm)**.
2. Пошук → **EC2** → ліве меню **Network & Security → Key Pairs** → **Create key pair**.
3. Name: `parcs-key`, Key pair type: **ED25519**, Private key file format: **.pem** → **Create key pair**.
   Файл `parcs-key.pem` завантажиться автоматично.
4. **[Mac]** перемісти ключ у безпечне місце (НЕ в папку проєкту!) і обмеж права:
   ```bash
   mkdir -p ~/.ssh && mv ~/Downloads/parcs-key.pem ~/.ssh/ && chmod 400 ~/.ssh/parcs-key.pem
   ```

### A2. Security group
1. EC2 → **Network & Security → Security Groups** → **Create security group**.
2. Security group name: `parcs-sg`, Description: `PARCS cluster`, VPC: залиш за замовчуванням.
3. **Inbound rules → Add rule** (два правила):
   | Type | Port | Source | Description |
   |---|---|---|---|
   | SSH | 22 | **My IP** | ssh from my computer |
   | Custom TCP | 8080 | **My IP** | PARCS web UI |
4. Outbound rules не чіпай → **Create security group**.
5. Відкрий щойно створену `parcs-sg` → вкладка **Inbound rules** → **Edit inbound rules** → **Add rule**:
   Type **All traffic**, Source **Custom** → почни вводити `parcs-sg` і вибери саму цю групу (`sg-...`),
   Description `cluster internal` → **Save rules**.
   (Вузли PARCS спілкуються на випадкових портах, тому всередині групи дозволено все, а ззовні — лише 22 і 8080 з твоєї IP.)

> Якщо твоя домашня IP зміниться (роутер перезавантажився, інша мережа), SSH почне «висіти» —
> онови два правила з **My IP** так само через Edit inbound rules.

### A3. Master-VM
EC2 → **Instances** → **Launch instances**:
1. Name: `parcs-master`.
2. Application and OS Images: **Ubuntu** → **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type**,
   Architecture **64-bit (x86)**. Має бути позначка *Free tier eligible*.
3. Instance type: **c7i-flex.large** (позначка *Free tier eligible*).
   Якщо його немає в списку — `t3.small`, і тоді в п. 7 обов'язково *Credit specification* = **Standard**.
4. Key pair: `parcs-key`.
5. Network settings → **Edit**: Auto-assign public IP **Enable**; Firewall → **Select existing security group** → `parcs-sg`.
6. Configure storage: залиш 8 GiB gp3.
7. **Advanced details** (внизу) → поле **User data**: встав увесь вміст файлу `deploy/user-data-master.sh`.
8. Праворуч Number of instances = 1 → **Launch instance**.
9. Instances → вибери `parcs-master` → запиши **Public IPv4 address** (`MASTER_PUBLIC_IP`) і
   **Private IPv4 addresses** (`MASTER_PRIVATE_IP`).

### A4. Worker-VM (усі одразу)
1. Відкрий `deploy/user-data-worker.sh`, заміни `MASTER_PRIVATE_IP` у рядку
   `MASTER_PRIVATE_IP="MASTER_PRIVATE_IP"` на справжню приватну IP master'а, наприклад
   `MASTER_PRIVATE_IP="172.31.12.34"`.
2. **Launch instances** ще раз з тими самими параметрами, що й A3, але:
   Name `parcs-worker`, User data — відредагований `user-data-worker.sh`,
   праворуч **Number of instances = W** (6 або 4).
3. **Launch instance**. Усі W машин отримають ім'я `parcs-worker` — це нормально.

### A5. Перевірка
Зачекай 3–5 хвилин (встановлення Docker і завантаження образу).
1. У браузері відкрий `http://MASTER_PUBLIC_IP:8080` → вкладка **Workers**: мають бути W воркерів
   з IP 172.31.x.x. Зроби **скріншот** (для звіту).
2. **[Mac]** зайди на master:
   ```bash
   ssh -i ~/.ssh/parcs-key.pem ubuntu@MASTER_PUBLIC_IP
   ```
   (на питання `Are you sure you want to continue connecting` відповідай `yes`)
3. **[master]**
   ```bash
   docker ps
   curl -s http://localhost:8080/api/worker | python3 -m json.tool
   ```
   Якщо `docker ps` порожній або команди немає — дивись лог: `sudo tail -50 /var/log/cloud-init-output.log`.

---

## Частина B. Експерименти

### B1. Копіювання коду на master
**[Mac]** з папки проєкту:
```bash
cd ~/Projects/blowfish
tar czf /tmp/blowfish-code.tgz src scripts deploy tests
scp -i ~/.ssh/parcs-key.pem /tmp/blowfish-code.tgz ubuntu@MASTER_PUBLIC_IP:~
```
**[master]**
```bash
mkdir -p ~/blowfish && cd ~/blowfish && tar xzf ~/blowfish-code.tgz
python3 scripts/build_solver.py
```

### B2. Інформація про середовище (для звіту)
**[master]** (через пробіл — приватні IP кількох воркерів, з вкладки Workers):
```bash
bash deploy/collect_env.sh 172.31.AAA.AAA 172.31.BBB.BBB | tee results_env.txt
```

### B3. Пробний запуск (1 МБ, ~1 хв)
**[master]** (`0 1 2 ... W` — заміни на свій список, напр. `0 1 2 3 4 5 6`):
```bash
python3 scripts/gen_data.py --sizes 1 --workers 0 1 2 3 4 5 6 --repeats 1 --out-dir data/smoke
python3 scripts/run_experiments.py --raw-out results/smoke_raw.csv --summary-out results/smoke_summary.csv data/smoke/job_1mb.bin
```
В останній колонці `match` усюди має бути `1`.

### B4. Основна серія
**[master]**
```bash
python3 scripts/gen_data.py --sizes 1 4 16 32 --workers 0 1 2 3 4 5 6 --repeats 3
nohup python3 scripts/run_experiments.py data/job_1mb.bin data/job_4mb.bin data/job_16mb.bin data/job_32mb.bin > results/run.log 2>&1 &
tail -f results/run.log
```
`nohup` — серія продовжиться, навіть якщо SSH-з'єднання обірветься. `Ctrl+C` зупиняє лише перегляд
логу, не саму серію. Повернутися до логу: `tail -f ~/blowfish/results/run.log`.
Поки йде серія, зроби **скріншот** вкладки **Jobs** у веб-інтерфейсі.

### B5. Забрати результати
**[Mac]**
```bash
cd ~/Projects/blowfish && mkdir -p results
scp -i ~/.ssh/parcs-key.pem "ubuntu@MASTER_PUBLIC_IP:~/blowfish/results/*" results/
scp -i ~/.ssh/parcs-key.pem ubuntu@MASTER_PUBLIC_IP:~/blowfish/results_env.txt results/
```

---

## Частина C. Видалення всіх ресурсів (ОБОВ'ЯЗКОВО після експериментів)

1. **EC2 → Instances**: виділи всі `parcs-master` і `parcs-worker` → **Instance state → Terminate (delete) instance** → підтверди.
   Зачекай, поки стан стане **Terminated**.
2. **EC2 → Elastic Block Store → Volumes**: список має бути порожнім (диски видаляються разом з інстансами).
   Якщо щось лишилось у стані *available* → **Actions → Delete volume**.
3. **EC2 → Network & Security → Elastic IPs**: має бути порожньо (ми їх не створювали). Якщо є — **Release**.
4. **EC2 → Security Groups**: вибери `parcs-sg` → **Actions → Delete security groups**.
   (Групу `default` не чіпай — її видалити не можна і вона безкоштовна.)
5. **EC2 → Key Pairs**: `parcs-key` → **Actions → Delete**; **[Mac]** `rm ~/.ssh/parcs-key.pem`.
6. Перевір усі регіони: EC2 → ліве меню **EC2 Global View** → лічильники Instances / Volumes мають бути 0.
7. Перевір кредити: пошук → **Billing and Cost Management** → на головній сторінці блок
   **Free plan / Credits** (залишок кредитів і днів). Через добу перевір **Bills** або **Cost Explorer**:
   після видалення витрати мають перестати рости.
