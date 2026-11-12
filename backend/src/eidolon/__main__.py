"""The `eidolon` command: runs the server, and lets the admin manage users.

    eidolon                          run the server (same as `eidolon serve`)
    eidolon user list                every user: id, name, sign-in methods (each with the
                                     `provider:subject` EIDOLON_ADMINS lists), when made,
                                     whether banned (users are made by signing in)
    eidolon user ban <id> [--note …] ban a user, with a note only admins see, signing them
                                     out everywhere; the server hangs up their calls within
                                     seconds (the same as banning in the admin console)
    eidolon user unban <id>
    eidolon user usage <id>          the user's text turns and calls in the last 24 hours,
                                     by hour, and how many were on their own keys; the last
                                     7 and 30 days are in the admin console's user details
    eidolon backup [--source cron]   back the database up, compressed and encrypted to the
                                     deployer's age key, to the private bucket, and delete
                                     the backups past the retention save the newest,
                                     recording the run; exits 2 if the copy failed, 3 if
                                     the upload did, 4 if deleting the old ones did, 6 if
                                     another backup was under way
    eidolon restore [--check] <file> put the database in a backup the deployer decrypted,
                                     .db or .db.gz, in place of this one, with the server
                                     stopped (deploy/db-restore.sh), if it is whole and has
                                     this project's tables, leaving it alone if not; and
                                     say how many users it has; --check only checks it
    eidolon doctor [--json]          try each service .env configures, the way the server
                                     reaches it, through the proxy and direct, and say
                                     what is wrong and what to change; exits 1 if anything
                                     is (docs/deploy.md)

Characters are made and edited through the API, not here: the platform ships no bundled
content, and every model runs on the user's own key.
"""

import argparse
import asyncio
import io
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from eidolon.clock import utc_now
from eidolon.config import Settings, UsageLimits, database_path_from_env
from eidolon.data_access import Database
from eidolon.identity import PROVIDER_LABELS
from eidolon.store import NotFound, Store
from eidolon.usage import Tally, UsageLimiter


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # a Windows console's code page (GBK) has no ✓ nor ✗: shown as ?, not failed on
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in (None, "serve"):
        return _serve()
    if args.command == "doctor":
        from eidolon.doctor import run

        return asyncio.run(run(args.json))
    if args.command == "backup":
        return asyncio.run(_backup(args))
    if args.command == "restore":
        return _restore(args)

    return asyncio.run(_user_command(args))


async def _user_command(args: argparse.Namespace) -> int:
    from eidolon.data_access import Database

    db = Database(args.db or database_path_from_env())
    try:
        await args.run(db, args)
    except NotFound as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        await db.close()
    return 0


GRACEFUL_SHUTDOWN_SECONDS = 20
"""How long, in seconds, requests under way are given to finish as the server stops; within
the grace compose gives it (`stop_grace_period` in docker-compose.prod.yml)."""


def _serve() -> int:
    import uvicorn
    from loguru import logger

    from eidolon import server_logs
    from eidolon.app import create_app
    from eidolon.assembly import build

    # Pipecat logs through loguru, which shows everything down to DEBUG unless told
    # otherwise: what users said, and what calls send to services on their own keys.
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    server_logs.configure()

    try:  # missing settings, an unusable DashScope key or Cloudflare token
        settings = Settings.from_env()
        settings = asyncio.run(_find_dashscope_region(settings))
        asyncio.run(_check_judge(settings))
        backend = build(settings)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    try:  # an unfit chat model, where the deployment configures one at all
        asyncio.run(_check_chat_llm(settings))
    except RuntimeError as e:
        asyncio.run(backend.aclose())
        print(e, file=sys.stderr)
        return 1
    app = create_app(backend)
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_config=server_logs.uvicorn_log_config(),
        # Calls are no requests: they are hung up after, as the backend closes.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    return 0


async def _find_dashscope_region(settings: Settings) -> Settings:
    """The settings with the region the deployer's DashScope key works in, found by trying
    it, if Alibaba Cloud Model Studio is to hear calls on it; raises RuntimeError saying
    why, if it cannot."""
    from eidolon.bailian import BailianCheckFailed, find_region

    key = settings.stt_key
    if key is None or key.provider != "bailian":
        return settings
    try:
        region = await find_region(
            key.api_key, settings.bailian_stt_model, settings.proxy.proxy_for("stt")
        )
    except BailianCheckFailed as e:
        raise RuntimeError(f"阿里云百炼的 DASHSCOPE_API_KEY 用不了：{e}") from None
    return replace(settings, dashscope_region=region)


async def _check_judge(settings: Settings) -> None:
    """Tries Cloudflare's credentials, through the proxy or direct, as `.env` has it."""
    from eidolon.judge import JUDGE_TIMEOUT, check_judge
    from eidolon.proxy import open_client

    async with open_client(settings.proxy.proxy_for("judge"), JUDGE_TIMEOUT) as client:
        await check_judge(settings.judge, client)


async def _check_chat_llm(settings: Settings) -> None:
    """Checks the chat model on a client of its own, through the proxy or direct, as
    `.env` has it: the server's run in uvicorn's event loop, and an HTTP client cannot
    move between loops. A zero-key deployment configures none, and has nothing to check:
    every turn runs on the user's own key."""
    if settings.chat_model is None:
        return
    from eidolon.llm.providers import LLM_TIMEOUT, check_chat_models, open_chat_models
    from eidolon.proxy import open_client

    proxy = settings.proxy.proxy_for("chat_llm")
    models = open_chat_models(settings.chat_model, open_client(proxy, LLM_TIMEOUT))
    try:
        await check_chat_models(models, settings.chat_model)
    finally:
        await models.aclose()


async def _backup(args: argparse.Namespace) -> int:
    import sqlite3
    import time

    from eidolon.backup import EXPORT_FAILED, Backups, describe
    from eidolon.data_access import Database

    started = time.monotonic()
    try:
        db = Database(args.db or database_path_from_env())
        try:
            report = await Backups(db, utc_now).run(args.source)
        finally:
            await db.close()
    except sqlite3.Error as e:  # not a missing setting, which exiting 1 would say
        print(f"没有备份：备份记录写不进数据库：{e}", file=sys.stderr)
        return EXPORT_FAILED
    for wrong, line in describe(report):
        print(line, file=sys.stderr if wrong else sys.stdout)
    if report.config_error is not None or report.busy:
        return report.exit_code
    print(f"用时 {time.monotonic() - started:.0f} 秒")
    return report.exit_code


def _restore(args: argparse.Namespace) -> int:
    from eidolon.restore import NotRestored, check, restore

    database = args.db or database_path_from_env()
    try:
        if args.check:
            users = check(args.file, database)
            print(f"{args.file} 通过了检查，库里有 {users} 位用户")
            return 0
        restored = restore(args.file, database, utc_now)
    except (NotRestored, OSError) as e:  # OSError: the rename
        print(f"没有恢复，现在的数据库没有换：{e}", file=sys.stderr)
        return 1
    print(f"已用 {args.file} 替换 {database}，恢复进来的库里有 {restored.users} 位用户")
    if restored.abandoned:
        print(f"备份时正在进行的 {restored.abandoned} 条备份记录已标成没有完成")
    return 0


async def _list_users(db: Database, _: argparse.Namespace) -> None:
    store = Store(db)
    users = await store.list_users()
    methods_of = await store.sign_in_methods_of([user.id for user in users])
    for user in users:
        methods = "、".join(
            f"{PROVIDER_LABELS.get(m.provider, m.provider)} {m.display_name}"  # pyright: ignore[reportCallIssue, reportArgumentType]
            f" ({m.provider}:{m.subject})"
            for m in methods_of[user.id]
        ) or "（没有登录方式）"
        state = f"已封禁于 {user.banned_at}" if user.banned_at else "正常"
        if user.ban_note:
            state += f"（备注：{user.ban_note}）"
        print(f"{user.id}\t{user.name}\t{methods}\t创建于 {user.created_at}\t{state}")


async def _ban_user(db: Database, args: argparse.Namespace) -> None:
    await Store(db).set_banned(args.user_id, datetime.now(UTC), args.note or None)
    print(f"已封禁用户 {args.user_id}，并让他在所有设备上退出登录；正在进行的通话会在几秒内挂断")


async def _unban_user(db: Database, args: argparse.Namespace) -> None:
    await Store(db).set_banned(args.user_id, None)
    print(f"已解封用户 {args.user_id}")


async def _user_usage(db: Database, args: argparse.Namespace) -> None:
    await Store(db).get_user(args.user_id)  # NotFound for no such user
    # The limits play no part in looking over what was used.
    day = await UsageLimiter(db, UsageLimits(), utc_now).last_day(args.user_id)
    print(f"用户 {args.user_id} 最近 24 小时的用量（UTC，按小时）：")
    print("时间\t文字回合\t通话\t其中不计入限额的回合\t其中不计入限额的通话")
    for hour, tally in day.hours.items():
        print(f"{hour:%Y-%m-%d %H:00}\t{_tally_columns(tally)}")
    print(f"合计\t{_tally_columns(day.total)}")


def _tally_columns(tally: Tally) -> str:
    return f"{tally.turns}\t{tally.calls}\t{tally.exempt_turns}\t{tally.exempt_calls}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eidolon", description="Eidolon 后端")
    parser.add_argument(
        "--db", type=Path, help="数据库文件（默认取环境变量 EIDOLON_DATABASE_PATH）"
    )
    commands = parser.add_subparsers(dest="command", metavar="命令")
    commands.add_parser("serve", help="启动服务（默认）")
    doctor = commands.add_parser(
        "doctor",
        help="按 .env 逐项试一次各项服务（经代理和直连），说明哪里不对、该怎么改"
        "（后端不用停，也不必在运行）",
    )
    doctor.add_argument("--json", action="store_true", help="结果输出成 JSON，给 Agent 读")

    user = commands.add_parser("user", help="管理用户").add_subparsers(
        dest="action", required=True, metavar="操作"
    )
    user.add_parser(
        "list", help="列出所有用户：ID、名字、登录方式（括号里是填进 EIDOLON_ADMINS 的标识）、创建时间、是否已封禁"
    ).set_defaults(run=_list_users)
    ban = user.add_parser("ban", help="封禁用户，并让他在所有设备上退出登录")
    ban.add_argument("user_id", help="用户 ID（见 user list）")
    ban.add_argument("--note", help="封禁的原因，只有管理者看得到（user list 和后台里显示）")
    ban.set_defaults(run=_ban_user)
    unban = user.add_parser("unban", help="解除封禁")
    unban.add_argument("user_id", help="用户 ID（见 user list）")
    unban.set_defaults(run=_unban_user)
    usage = user.add_parser(
        "usage",
        help="查看用户最近 24 小时按小时统计的用量（最近 7 天、30 天的用量在后台的用户详情里看）",
    )
    usage.add_argument("user_id", help="用户 ID（见 user list）")
    usage.set_defaults(run=_user_usage)

    backup = commands.add_parser(
        "backup",
        help="把数据库压缩、用 age 公钥加密后备份到私有的存储桶，并删掉过了保留期（默认 30 天）的备份，"
        "最新的一份总是保留（存储桶、公钥和保留期取环境变量 EIDOLON_BACKUP_*；"
        "导出失败退出码为 2，上传失败为 3，删除过期备份失败为 4，上一次备份还没结束为 6）",
    )
    backup.add_argument(
        "--source",
        choices=["manual", "cron"],
        default="manual",
        help="谁发起的这次备份，记进备份记录、显示在看板上（默认 manual；主机上的 cron 传 cron）",
    )

    restore = commands.add_parser(
        "restore",
        help="用在自己电脑上解密好的备份（.db 或 .db.gz）替换数据库，要先停后端"
        "（服务器上用 deploy/db-restore.sh）；文件损坏、不是 SQLite 或者不是本项目的数据库时什么都不动，"
        "退出码为 1",
    )
    restore.add_argument("file", type=Path, help="解密后的备份文件，压缩的和解压后的都行")
    restore.add_argument(
        "--check",
        action="store_true",
        help="只检查文件、报出用户数，不替换（不用停后端；deploy/db-restore.sh 先这样检查一遍）",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())