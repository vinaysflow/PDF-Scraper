"""Ingest a QuestionBank into Supabase (Postgres + Storage).

Uploads images to Supabase Storage and inserts structured data into
the Postgres tables defined in ``schema.sql``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..schema import QuestionBank
from .supabase_client import get_client

logger = logging.getLogger(__name__)

STORAGE_BUCKET = "question-images"


def ingest_question_bank(qbank: QuestionBank) -> dict[str, Any]:
    """Upload images to Storage, insert rows into Postgres.

    Parameters
    ----------
    qbank:
        The question bank to ingest.

    Returns
    -------
    Summary dict with counts of inserted rows and uploaded images.
    """
    client = get_client()

    # ------------------------------------------------------------------
    # 1. Insert document
    # ------------------------------------------------------------------
    doc_row = {
        "doc_id": qbank.doc_id,
        "filename": qbank.filename,
        "exam_title": qbank.exam_title,
        "subject": qbank.subject,
        "total_marks": qbank.total_marks,
        "total_questions": qbank.total_questions,
        "sections": qbank.sections,
        "ingested_at": qbank.ingested_at.isoformat(),
    }
    doc_resp = (
        client.table("documents")
        .upsert(doc_row, on_conflict="doc_id")
        .execute()
    )
    document_id = doc_resp.data[0]["id"]
    logger.info("Upserted document %s -> %s", qbank.doc_id, document_id)

    # ------------------------------------------------------------------
    # 2. Process each question
    # ------------------------------------------------------------------
    questions_inserted = 0
    options_inserted = 0
    images_uploaded = 0
    parts_inserted = 0

    for question in qbank.questions:
        # Insert main question
        q_row = {
            "document_id": document_id,
            "question_number": question.question_number,
            "section": question.section,
            "page_number": question.page_number,
            "text": question.text,
            "question_type": question.question_type,
            "marks": question.marks,
            "topic": question.topic,
            "difficulty": question.difficulty,
            "has_or_alternative": question.has_or_alternative,
        }

        q_resp = (
            client.table("questions")
            .upsert(q_row, on_conflict="document_id,question_number")
            .execute()
        )
        question_id = q_resp.data[0]["id"]
        questions_inserted += 1

        # Handle OR alternative
        or_question_id = None
        if question.has_or_alternative and question.or_question:
            or_q = question.or_question
            or_row = {
                "document_id": document_id,
                "question_number": or_q.question_number,
                "section": or_q.section,
                "page_number": or_q.page_number,
                "text": f"[OR] {or_q.text}",
                "question_type": or_q.question_type,
                "marks": or_q.marks,
                "topic": or_q.topic,
                "difficulty": or_q.difficulty,
                "has_or_alternative": False,
            }
            # Use a special question_number for OR alternatives to avoid
            # UNIQUE constraint collision: original * 1000
            or_row["question_number"] = question.question_number * 1000
            or_resp = (
                client.table("questions")
                .upsert(or_row, on_conflict="document_id,question_number")
                .execute()
            )
            or_question_id = or_resp.data[0]["id"]
            questions_inserted += 1

            # Link the OR alternative
            client.table("questions").update(
                {"or_question_id": or_question_id}
            ).eq("id", question_id).execute()

        # Insert options (MCQ)
        for idx, opt in enumerate(question.options):
            opt_row = {
                "question_id": question_id,
                "label": opt.label,
                "text": opt.text,
                "sort_order": idx,
            }
            client.table("question_options").insert(opt_row).execute()
            options_inserted += 1

        # Upload and insert images
        for img in question.images:
            storage_path, public_url = _upload_image(
                client, qbank.doc_id, question.question_number, img,
            )
            if storage_path:
                img_row = {
                    "question_id": question_id,
                    "storage_path": storage_path,
                    "public_url": public_url,
                    "format": img.format,
                    "width": img.width,
                    "height": img.height,
                    "description": img.description,
                    "bbox": img.bbox,
                }
                client.table("question_images").insert(img_row).execute()
                images_uploaded += 1

        # Insert sub-parts
        for idx, part in enumerate(question.sub_parts):
            part_row = {
                "question_id": question_id,
                "label": part.label,
                "text": part.text,
                "marks": part.marks,
                "sort_order": idx,
            }
            client.table("question_parts").insert(part_row).execute()
            parts_inserted += 1

    summary = {
        "document_id": document_id,
        "doc_id": qbank.doc_id,
        "questions_inserted": questions_inserted,
        "options_inserted": options_inserted,
        "images_uploaded": images_uploaded,
        "parts_inserted": parts_inserted,
        "supabase_url": f"{client.supabase_url}",
    }
    logger.info("Ingestion complete: %s", summary)
    return summary


def _upload_image(
    client: Any,
    doc_id: str,
    question_number: int,
    img: Any,
) -> tuple[str | None, str | None]:
    """Upload a single image to Supabase Storage.

    Returns (storage_path, public_url) or (None, None) if upload fails.
    """
    image_path = img.image_path
    if not image_path or not os.path.exists(image_path):
        logger.warning(
            "Image file not found for Q%d: %s", question_number, image_path,
        )
        return None, None

    # Storage path: question-images/{doc_id}/q{N}/filename
    filename = Path(image_path).name
    storage_path = f"{doc_id}/q{question_number}/{filename}"

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # Upload to Supabase Storage
        client.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=image_bytes,
            file_options={"content-type": f"image/{img.format}"},
        )

        # Get public URL
        public_url_resp = client.storage.from_(STORAGE_BUCKET).get_public_url(
            storage_path,
        )
        public_url = public_url_resp if isinstance(public_url_resp, str) else None

        logger.info("Uploaded image to %s", storage_path)
        return storage_path, public_url

    except Exception as e:
        logger.error("Failed to upload image %s: %s", storage_path, e)
        return None, None
