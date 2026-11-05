#!/bin/sh
# INF-004 · тестовые данные AD для автотестов AUTH и QA-012 (SPEC 17.1, Q-50; TC-AUTH-01/02).
# Только синтетические учётки, без реальных ПДн. Пароль у всех — SAMBA_TEST_PASSWORD.
#
# OU=Estimator
# ├─ OU=Users        пользователи
# ├─ OU=Disabled     отключённые учётки (ACCOUNTDISABLE)
# ├─ OU=Service      сервисная учётка приложения (FR-AUTH-AD-01)
# └─ OU=Groups       группы доступа и ролей
#
# Группы: est-access (доступ к приложению) ← est-experts ← est-presale-team (вложенность 2
# уровня), est-moderators ⊂ est-access, est-presale-leads ⊂ est-access.
set -eu
: "${BASE_DN:?}"
P="$SAMBA_TEST_PASSWORD"
ROOT="OU=Estimator,$BASE_DN"
tool() { samba-tool "$@" -H /var/lib/samba/private/sam.ldb; }

tool ou create "$ROOT" --description="Тестовые данные приложения оценки"
for ou in Users Disabled Service Groups; do tool ou create "OU=$ou,$ROOT"; done

group() { tool group add "$1" --groupou="OU=Groups,OU=Estimator" --description="$2"; }
group est-access "Доступ к приложению"
group est-experts "Эксперты"
group est-moderators "Модераторы"
group est-presale-team "Пресейл (вложена в экспертов)"
group est-presale-leads "Руководители пресейла"
group est-unrelated "Группа без доступа"
tool group addmembers est-access est-experts,est-moderators,est-presale-leads
tool group addmembers est-experts est-presale-team

user() {  # логин, имя, фамилия, OU
  tool user create "$1" "$P" --given-name="$2" --surname="$3" \
    --mail-address="$1@test.estimator.local" --userou="OU=$4,OU=Estimator" \
    --use-username-as-cn
}
user svc-estimator Service Estimator Service
user expert.one Expert One Users
user expert.nested Expert Nested Users
user moderator.one Moderator One Users
user presale.lead Presale Lead Users
user no.access Nobody Access Users
user rename.me Rename Me Users
user disabled.one Disabled One Disabled

tool group addmembers est-experts expert.one
tool group addmembers est-presale-team expert.nested
tool group addmembers est-moderators moderator.one
tool group addmembers est-presale-leads presale.lead
tool group addmembers est-access rename.me,disabled.one
tool group addmembers est-unrelated no.access
tool user disable disabled.one

# UPN с другим суффиксом — проверка входа по userPrincipalName (FR-AUTH-AD-01)
cat > /tmp/upn.ldif <<LDIF
dn: CN=expert.one,OU=Users,$ROOT
changetype: modify
replace: userPrincipalName
userPrincipalName: e.one@corp.test.estimator.local
LDIF
ldbmodify -H /var/lib/samba/private/sam.ldb /tmp/upn.ldif
rm -f /tmp/upn.ldif
