# Публикация нового репозитория на GitHub

**Задуманное имя:** `maxliv234-star/DiscForge-RU` (публичный, MIT). Не путать с уже существующим `pdfcraft`.

Подключённый к чату GitHub API умеет читать/менять файлы существующих репозиториев, но **не умеет создавать новый репозиторий**. Поэтому этот архив готов к публикации, но ссылку считать действующей нельзя, пока репозиторий не создан.

## Вариант без команд

1. Откройте https://github.com/new
2. Владелец: `maxliv234-star`; имя: `DiscForge-RU`.
3. Visibility: **Public**. НЕ ставьте галочки README / LICENSE / .gitignore — они уже есть в архиве.
4. Создайте пустой репозиторий.
5. В PowerShell из распакованной папки проекта выполните:

```powershell
git init
git add .
git commit -m "Initial DiscForge RU alpha"
git branch -M main
git remote add origin https://github.com/maxliv234-star/DiscForge-RU.git
git push -u origin main
```

## Вариант GitHub CLI

Если установлен и выполнен вход в `gh`:

```powershell
cd путь\к\DiscForge_RU_v0.1
git init
git add .
git commit -m "Initial DiscForge RU alpha"
git branch -M main
gh repo create maxliv234-star/DiscForge-RU --public --source . --remote origin --push
```

Сначала проверяйте, что отправляете исходники, а не личные фильмы/ISO. Бинарники сторонних инструментов не включены.
