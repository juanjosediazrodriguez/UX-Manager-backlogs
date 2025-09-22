from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.timesince import timesince

from apps.feedback.models import CompanyComment

from .company_data import COMPANIES

COMPANY_MAP: Dict[str, dict] = {company["slug"]: company for company in COMPANIES}

COMMENT_FILTER_RULES: Dict[str, Tuple[int, int]] = {
    "todos": (1, 5),
    "buenos": (4, 5),
    "regulares": (3, 3),
    "malos": (1, 2),
}

COMMENT_FILTER_LABELS: Dict[str, Dict[str, str]] = {
    "todos": {"label": "Todos", "description": "Vista general"},
    "buenos": {"label": "Buenos", "description": "4 a 5 estrellas"},
    "regulares": {"label": "Regulares", "description": "3 estrellas"},
    "malos": {"label": "Malos", "description": "1 a 2 estrellas"},
}

COMMENT_FILTER_ORDER = ["todos", "buenos", "regulares", "malos"]


def _match_company(company: dict, query: str) -> bool:
    query_lower = query.lower()
    fields_to_search: List[str] = [
        company["name"],
        company["industry"],
        company["location"],
        " ".join(company.get("tags", [])),
        company.get("summary_line", ""),
    ]
    return any(query_lower in field.lower() for field in fields_to_search if field)


def _filter_comments(comments: List[dict], key: str) -> List[dict]:
    key = key if key in COMMENT_FILTER_RULES else "todos"
    min_rating, max_rating = COMMENT_FILTER_RULES[key]
    filtered = [comment for comment in comments if min_rating <= comment.get("rating", 0) <= max_rating]
    return sorted(filtered, key=lambda c: c.get("sort_key", (1, 0)), reverse=True)


def _count_by_filter(comments: List[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for filter_key, (min_rating, max_rating) in COMMENT_FILTER_RULES.items():
        counts[filter_key] = sum(
            1 for comment in comments if min_rating <= comment.get("rating", 0) <= max_rating
        )
    return counts


def _humanize_timesince(value: datetime) -> str:
    delta = timesince(value, timezone.now())
    delta = delta.replace("\xa0", " ")
    if not delta:
        return "Hace instantes"
    main = delta.split(",")[0].strip()
    if not main:
        return "Hace instantes"
    return f"Hace {main}"


def _serialize_user_comment(comment: CompanyComment) -> dict:
    author = comment.user.get_full_name() or comment.user.email or comment.user.username
    return {
        "id": comment.id,
        "author": author,
        "quote": comment.comment,
        "rating": comment.rating,
        "responses_label": "0 respuestas",
        "timestamp_label": _humanize_timesince(comment.created_at),
        "sort_key": (1, comment.created_at.timestamp()),
        "is_user": True,
    }


def _serialize_mock_comment(comment: dict) -> dict:
    return {
        "author": comment.get("author", "Anonimo"),
        "quote": comment.get("quote", ""),
        "rating": comment.get("rating", 0),
        "responses_label": f"{comment.get('responses', 0)} respuestas",
        "timestamp_label": comment.get("timestamp", ""),
        "sort_key": (0, 0),
        "is_user": False,
    }


def home(request):
    query = request.GET.get("q", "").strip()
    has_query = bool(query)

    total_companies = len(COMPANIES)
    top_companies = sorted(
        COMPANIES, key=lambda c: (-c["avg_rating"], -c["review_count"])
    )[:6]

    if has_query:
        filtered = [company for company in COMPANIES if _match_company(company, query)]
    else:
        filtered = []

    search_results = filtered[:12]

    context = {
        "query": query,
        "has_query": has_query,
        "result_count": len(filtered),
        "search_results": search_results,
        "total_companies": total_companies,
        "top_companies": top_companies,
    }

    return render(request, "home.html", context)


def company_ratings(request, slug: str):
    company = COMPANY_MAP.get(slug)
    if company is None:
        raise Http404("Empresa no encontrada")

    selected_filter = request.GET.get("comentarios", "todos")
    if request.method == "POST":
        selected_filter = request.POST.get("comentarios", selected_filter)

    if selected_filter not in COMMENT_FILTER_RULES:
        selected_filter = "todos"

    form_errors: List[str] = []
    if request.method == "POST":
        if not request.user.is_authenticated:
            login_url = f"{reverse('account_login')}?{urlencode({'next': request.get_full_path()})}"
            return redirect(login_url)

        comment_text = request.POST.get("comment", "").strip()
        rating_raw = request.POST.get("rating", "").strip()

        if not comment_text:
            form_errors.append("El comentario no puede estar vacio.")

        try:
            rating_value = int(rating_raw)
        except (TypeError, ValueError):
            form_errors.append("Selecciona una calificacion valida.")
            rating_value = None
        else:
            if rating_value < 1 or rating_value > 5:
                form_errors.append("La calificacion debe ser entre 1 y 5 estrellas.")

        if not form_errors and rating_value is not None:
            CompanyComment.objects.create(
                user=request.user,
                company_slug=slug,
                company_name=company["name"],
                rating=rating_value,
                comment=comment_text,
            )

            # Redirige para evitar reenvio del formulario.
            if rating_value >= 4:
                redirect_filter = "buenos"
            elif rating_value == 3:
                redirect_filter = "regulares"
            elif rating_value <= 2:
                redirect_filter = "malos"
            else:
                redirect_filter = "todos"

            query_params = {"comentarios": redirect_filter} if redirect_filter != "todos" else {}
            return redirect(f"{request.path}?{urlencode(query_params)}" if query_params else request.path)

    user_comments_qs = CompanyComment.objects.filter(company_slug=slug).select_related("user")
    user_comments = [_serialize_user_comment(comment) for comment in user_comments_qs]

    mock_comments_raw = company.get("recent_comments", [])
    mock_comments = [_serialize_mock_comment(comment) for comment in mock_comments_raw]

    combined_comments = user_comments + mock_comments
    combined_comments.sort(key=lambda c: c.get("sort_key", (1, 0)), reverse=True)

    ratings = [comment.get("rating") for comment in combined_comments if comment.get("rating")]
    comment_average = round(sum(ratings) / len(ratings), 1) if ratings else round(company["avg_rating"], 1)
    total_comment_count = len(combined_comments)

    rating_distribution = []
    for star in range(5, 0, -1):
        star_count = sum(1 for rating in ratings if rating == star)
        percentage = round((star_count / total_comment_count) * 100) if total_comment_count else 0
        rating_distribution.append({"label": f"{star} estrellas" if star != 1 else "1 estrella", "count": star_count, "percentage": percentage})

    comment_counts = _count_by_filter(combined_comments)
    filtered_comments = _filter_comments(combined_comments, selected_filter)

    base_path = request.path
    comment_filters = []
    for filter_key in COMMENT_FILTER_ORDER:
        meta = COMMENT_FILTER_LABELS[filter_key]
        if filter_key == "todos":
            url = base_path
        else:
            url = f"{base_path}?{urlencode({'comentarios': filter_key})}"
        comment_filters.append(
            {
                "key": filter_key,
                "label": meta["label"],
                "description": meta["description"],
                "count": comment_counts.get(filter_key, 0),
                "is_active": filter_key == selected_filter,
                "url": url,
            }
        )

    score_percent = max(0, min(100, (comment_average / 5) * 100))

    industry_companies = [c for c in COMPANIES if c["industry"] == company["industry"]]
    industry_average = round(
        sum(c["avg_rating"] for c in industry_companies) / len(industry_companies), 1
    )

    related_companies = [
        c for c in industry_companies if c["slug"] != company["slug"]
    ]
    related_companies = sorted(related_companies, key=lambda c: (-c["avg_rating"], -c["review_count"]))[:4]

    context = {
        "company": company,
        "score_percent": score_percent,
        "industry_average": industry_average,
        "industry_size": len(industry_companies),
        "related_companies": related_companies,
        "comment_filters": comment_filters,
        "selected_comment_filter": selected_filter,
        "filtered_comments": filtered_comments,
        "total_comment_count": total_comment_count,
        "comment_average": comment_average,
        "rating_distribution": rating_distribution,
        "form_errors": form_errors,
        "has_user_comments": bool(user_comments),
    }

    return render(request, "calificaciones.html", context)
