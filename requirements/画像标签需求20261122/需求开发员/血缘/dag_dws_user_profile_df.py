"""Airflow DAG：dws_user_profile_df 日更（REQ-20261122-02）。

调度：每天 03:00（Asia/Shanghai），T+1 口径——${dt} 为调度日，业务数据取到 dt-1。
依赖链：tag_dict_source → dim_tag_df → dws_user_profile_df → dq。

三个任务：
  sync_dim_tag_df            标签字典落地（列名与值域的唯一权威）
  etl_dws_user_profile_df    INSERT OVERWRITE PARTITION(dt)，幂等
  dq_dws_user_profile_df     12 条断言，任一条返回非 0 就失败（不阻断已写入分区，只阻断下游发布）

为什么不把质检写成 BashOperator + grep：
  dq_check.sql 的每条断言返回一个数字或若干行，grep 判断"全是 0"很脆；
  用 PythonOperator 逐条解析，失败时把规则 id 打进日志，定位快。
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

SQL_DIR = "/opt/dw/sql/画像标签需求20261122"
HIVE = "hive"
DAG_ID = "profile_dws_user_profile_df"

default_args = {
    "owner": "data-eng",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,
}


def run_dq(ds: str, **_) -> None:
    """执行 dq_check.sql，任一条断言不通过就抛错。"""
    proc = subprocess.run(
        [HIVE, "-hivevar", f"dt={ds}", "-f", f"{SQL_DIR}/需求开发员/质量/dq_check.sql"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Hive 执行失败：{proc.stderr[-2000:]}")

    # Hive 会打印进度日志，只取纯数字/制表符的结果行
    values = [ln.strip() for ln in proc.stdout.splitlines()
              if ln.strip() and all(c.isdigit() or c in "\t. " for c in ln.strip())]
    bad = [v for v in values if v and v.split("\t")[0] not in ("0", "0.0")]
    if bad:
        raise ValueError(f"DQ 未通过（{len(bad)} 条）：{bad[:5]}")


with DAG(
    dag_id=DAG_ID,
    description="用户画像宽表日更（基础画像 + 购买行为画像）",
    default_args=default_args,
    start_date=datetime(2026, 11, 1),
    schedule_interval="0 3 * * *",
    catchup=False,          # 不回补历史，补数据走单独的一次性 DAG
    max_active_runs=1,      # 同一分区不允许并发写
    tags=["dws", "profile", "REQ-20261122-02"],
    doc_md=__doc__,
) as dag:

    sync_dim_tag_df = BashOperator(
        task_id="sync_dim_tag_df",
        bash_command=f"{HIVE} -hivevar dt={{{{ ds }}}} -f {SQL_DIR}/需求开发员/监督者/final/04_dim_tag_df_data.sql",
        doc="标签字典：列名、值域、display_order",
    )

    etl_dws_user_profile_df = BashOperator(
        task_id="etl_dws_user_profile_df",
        bash_command=f"{HIVE} -hivevar dt={{{{ ds }}}} -f {SQL_DIR}/需求开发员/监督者/final/03_etl_dws_user_profile_df.sql",
        doc="宽表全量快照，INSERT OVERWRITE 覆盖分区",
    )

    dq_dws_user_profile_df = PythonOperator(
        task_id="dq_dws_user_profile_df",
        python_callable=run_dq,
        op_kwargs={"ds": "{{ ds }}"},
        doc="12 条 DQ 断言",
    )

    sync_dim_tag_df >> etl_dws_user_profile_df >> dq_dws_user_profile_df
