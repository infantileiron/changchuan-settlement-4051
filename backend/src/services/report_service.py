from uuid import uuid4
from sqlalchemy import select
from fastapi import HTTPException
from ..models.review import MatchReview
from ..models.run import MatchRun
from ..models.report import Report
from .export_csv import build_reconciliation_csv

def create(db,body):
 review=db.get(MatchReview,body.review_id)
 if review is None or review.state!="approved":raise HTTPException(409,"报告须关联已批准匹配复核")
 existing=db.scalar(select(Report).where(Report.review_id==body.review_id))
 if existing:return existing
 run=db.get(MatchRun,review.run_id);row=Report(id=str(uuid4()),review_id=review.id,title=body.title,snapshot={"result":run.result,"action":review.action,"reviewer":review.reviewer});db.add(row);db.commit();return row

def export(row):
 # 底稿与归档共用同一纯函数口径，保证歧义说明展示一致；旧数据兼容读取。
 return build_reconciliation_csv(row.snapshot["result"])
