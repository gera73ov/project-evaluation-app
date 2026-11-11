"""``estimator project purge`` — физическое удаление проекта (CORE-090; BR-PRJ-04, GAP-12).

Порядок GAP-12: обязательные ``--ticket`` (номер заявки) и ``--approved-by`` (логин сотрудника
ИБ, согласовавшего удаление); сначала команда показывает состав удаляемого (dry-run), затем
просит ввести id проекта. ``--dry-run`` — только показать состав. Неверный id в подтверждении —
отказ без изменений. Каждый запуск — в аудит (``project.purged`` и ``system.cli.executed``) с
пользователем ОС. Логика — :mod:`estimator.services.projects.purge`.
"""

from __future__ import annotations

import asyncio
import uuid

import typer

project_app = typer.Typer(help="Проекты: физическое удаление (BR-PRJ-04).", no_args_is_help=True)

EXIT_REFUSED = 1
_PROJECT_ID = typer.Argument(..., help="id проекта (UUID).")

_LABELS = {
    "nodes": "узлов дерева",
    "threads": "обсуждений и вопросов",
    "messages": "сообщений",
    "notes": "заметок",
    "snapshots": "снимков",
    "documents": "документов заказчика",
    "exports": "файлов выгрузок",
}


def _show(target: object) -> None:
    from estimator.services.projects.purge import PurgePlan

    assert isinstance(target, PurgePlan)  # noqa: S101  # nosec B101 — тип результата
    typer.echo(f"Проект {target.project_id} «{target.project_name}». Будет удалено:")
    for key, value in target.composition.as_dict().items():
        typer.echo(f"  {_LABELS[key]}: {value}")
    typer.echo("Записи аудита остаются.")


def _run(project_id: uuid.UUID, *, ticket: str, approved_by: str, dry_run: bool) -> object:
    from estimator.cli import _os_user
    from estimator.db.session import dispose_engine, transaction
    from estimator.services.projects import purge

    async def main() -> object:
        try:
            async with transaction() as db:
                return await purge.purge(
                    db, project_id, ticket=ticket, approved_by=approved_by,
                    dry_run=dry_run, os_user=_os_user(),
                )  # fmt: skip
        finally:
            await dispose_engine()

    return asyncio.run(main())


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    app.add_typer(project_app, name="project")

    @command(
        "purge",
        group=project_app,
        group_name="project",
        help=(
            "Физически удалить проект по заявке, согласованной с ИБ: сначала состав (dry-run), "
            "затем подтверждение вводом id проекта. Аудит остаётся."
        ),
    )
    def purge_cmd(
        project_id: uuid.UUID = _PROJECT_ID,
        ticket: str = typer.Option(..., "--ticket", help="Номер заявки на удаление."),
        approved_by: str = typer.Option(
            ..., "--approved-by", help="Логин сотрудника ИБ, согласовавшего удаление."
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Только показать состав удаляемого, ничего не удалять."
        ),
    ) -> None:
        from estimator.services.projects.purge import PurgeError, PurgePlan, remove_files

        try:
            target = _run(project_id, ticket=ticket, approved_by=approved_by, dry_run=True)
            _show(target)
            if dry_run:
                typer.echo("Режим dry-run: ничего не удалено.")
                return
            typed = typer.prompt("Для удаления введите id проекта").strip()
            if typed != str(project_id):
                typer.echo("Отказ: id не совпадает, ничего не удалено.", err=True)
                raise typer.Exit(EXIT_REFUSED)
            done = _run(project_id, ticket=ticket, approved_by=approved_by, dry_run=False)
        except PurgeError as exc:
            typer.echo(f"Отказ: {exc}.", err=True)
            raise typer.Exit(EXIT_REFUSED) from exc
        assert isinstance(done, PurgePlan)  # noqa: S101  # nosec B101 — тип результата
        removed = remove_files(done)
        typer.echo(f"Проект {project_id} удалён. Файлов удалено с томов: {removed}.")
