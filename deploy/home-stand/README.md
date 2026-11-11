# Домашний стенд (INF-018)

Тестовый стенд проекта до появления серверов INF-011. Это отдельный домашний компьютер владельца
на Linux Mint, на котором работает свой исполнитель GitHub Actions (self-hosted runner) с меткой
`home-stand`. Решение принято 10.11.2026 (PLAN-1.6).

## Как это работает

1. Исполнитель — служба на компьютере. Она сама ходит **наружу** к GitHub и забирает задания:
   входящих подключений нет, порты на роутере не пробрасываются.
2. На PR с кодом (и по кнопке «Run workflow») GitHub ставит в очередь задание `e2e-stand`
   с меткой `home-stand`. Его может взять только домашний исполнитель.
3. Исполнитель скачивает код PR, собирает образы, поднимает весь стенд (`make up-test`: nginx,
   api, worker, beat, postgres, redis, ClamAV, Samba AD, Mailpit, syslog TLS), запускает сиды
   и все сценарии Playwright, а также наборы AD на Samba (QA-012).
4. Результат (галочка, отчёт Playwright, скриншоты, логи стенда) возвращается в GitHub.
   Стенд останавливается, тома удаляются, и компьютер снова ждёт.
5. PR с кодом тред вливает только после зелёного `e2e-stand`. PR только с документами и планом
   вливаются без e2e. Если компьютер выключен, задание висит в очереди, тред ждёт и пишет владельцу.

Агенты видят всё в GitHub, к самому компьютеру им доступ не нужен.

## Требования к компьютеру

| | Минимум | Лучше |
|---|---|---|
| Процессор | 4 ядра x86-64 | 6–8 ядер |
| Память | 8 ГБ | 16 ГБ |
| Диск | 50 ГБ свободно, SSD | 100 ГБ |
| ОС | Linux Mint 21/22 (база Ubuntu 22.04/24.04) | |
| Сеть | проводное подключение к роутеру | |

Самые тяжёлые части прогона — ClamAV (около 1,5 ГБ памяти) и браузеры Playwright.

## Быстрая установка одной командой

Скрипт `setup.sh` делает шаги 1–4 ниже сам (шаг 0 — настройка GitHub — остаётся за вами).

1. На Linux Mint скачайте скрипт:
   `cd ~ && curl -fsSLO https://raw.githubusercontent.com/gera73ov/project-evaluation-app/main/deploy/home-stand/setup.sh`
2. Получите токен: **Settings → Actions → Runners → New self-hosted runner → Linux, x64**,
   скопируйте значение после `--token` в строке `./config.sh`.
3. В терминале **своей** учётки (не `stand`):

   ```bash
   cd ~
   sudo bash setup.sh <ТОКЕН>
   ```

   `sudo` спросит ваш пароль. В конце скрипт напишет «Готово». Повторный запуск безопасен.
   Если что-то упадёт, пришлите последние строки вывода.

## Установка вручную

### 0. Защита публичного репозитория

Репозиторий публичный (решение владельца 11.11.2026: на приватном кончаются бесплатные минуты
облачного CI). GitHub не рекомендует свои исполнители для публичных репозиториев: PR из чужого
форка мог бы выполнить свой код на домашнем компьютере. Поэтому:

- **Settings → Actions → General → Fork pull request workflows** →
  **Require approval for all external contributors**: чужой PR не запустится без одобрения владельца;
- задания на `home-stand` запускаются только на PR из самого репозитория
  (`github.event.pull_request.head.repo.full_name == github.repository`) и по кнопке;
  на `pull_request_target` исполнитель не используется никогда;
- исполнитель работает под `stand` без `sudo`, на компьютере нет ничего ценного.

### 1. Подготовить систему

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y ca-certificates curl git make python3 unattended-upgrades ufw
sudo dpkg-reconfigure -plow unattended-upgrades     # автоматические обновления безопасности
sudo ufw default deny incoming && sudo ufw default allow outgoing && sudo ufw enable
```

Отключить сон и выключение экрана с блокировкой: **Параметры системы → Управление питанием →
«Переводить компьютер в режим сна» = Никогда** (при питании от сети).

### 2. Установить Docker Engine

Linux Mint ставит Docker из репозитория Ubuntu; кодовое имя берётся из `UBUNTU_CODENAME`.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Docker публикует порты в обход ufw, но все порты стенда в compose привязаны к `127.0.0.1`,
поэтому из домашней сети они не видны.

### 3. Завести пользователя для стенда

Отдельный пользователь без `sudo`, только в группе `docker`. Под ним работает исполнитель.
Пароля у него нет: входить в него только из своей учётки командой `sudo -iu stand`
(спросит твой пароль), выходить — `exit`.

```bash
sudo adduser --disabled-password --gecos "" stand
sudo usermod -aG docker stand
```

### 4. Установить исполнитель GitHub Actions

1. GitHub → репозиторий → **Settings → Actions → Runners → New self-hosted runner → Linux, x64**.
   GitHub покажет команды с актуальной версией и одноразовым токеном (он живёт около часа).
2. Выполнить их под пользователем `stand`:

   ```bash
   sudo -iu stand
   mkdir actions-runner && cd actions-runner
   # curl … и tar … — строки скачивания со страницы GitHub (с проверкой sha256)
   ./config.sh --url https://github.com/gera73ov/project-evaluation-app \
     --token <ТОКЕН_СО_СТРАНИЦЫ> --name home-mint --labels home-stand --unattended
   exit
   ```

3. Запустить как службу, которая стартует вместе с компьютером. Это делается **из своей
   учётки**, не из `stand`: у `stand` нет `sudo`, и внутри его сеанса `sudo` попросит пароль
   `stand`, которого нет. Приглашение терминала не должно начинаться со `stand@`.

   ```bash
   sudo bash -c 'cd /home/stand/actions-runner && ./svc.sh install stand && ./svc.sh start && ./svc.sh status'
   ```

   `status` должен показать `active (running)`.

4. Проверка: в **Settings → Actions → Runners** исполнитель `home-mint` с меткой `home-stand`
   в состоянии **Idle**.

### 5. Проверить стенд руками (по желанию)

```bash
sudo -iu stand
git clone https://github.com/gera73ov/project-evaluation-app.git && cd project-evaluation-app
make up-test && make smoke-test
make down
```


## Обслуживание

- Workflow `e2e-stand` после прогона удаляет тома (`down -v`) и старые образы
  (`docker image prune`); если диск всё равно заполняется — `docker system prune -af` под `stand`.
- Обновления исполнителя ставятся автоматически.
- Если компьютер долго был выключен, ничего делать не нужно: после включения служба заберёт
  задания из очереди.
- Отключить стенд: `sudo ./svc.sh stop` в `/home/stand/actions-runner`; удалить совсем —
  `sudo ./svc.sh uninstall`, затем удалить исполнитель в **Settings → Actions → Runners**.

## Рабочий компьютер владельца

На рабочем компьютере (Windows) стенд поднимается вручную через WSL2 (Docker Desktop или
Docker внутри Ubuntu в WSL) командой `make up-test`, чтобы посмотреть приложение в браузере.
Исполнитель туда не ставится.

## Что проверяется только здесь

- AD — только на Samba AD DC из профиля test. Корпоративный AD (тестовый OU, Q-50) проверяется
  вручную перед stage (RISK-07).
- Всё, что требует настоящего стенда: e2e FE-080, FE-090…FE-094, наборы QA-012.
