from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Tuple
import unicodedata
import difflib

import requests
from django.conf import settings
from django.db.models import Count, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.timesince import timesince
from django.views.decorators.http import require_POST

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


def _normalize(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


_INDUSTRY_LOOKUP: Dict[str, str] = {}
_LOCATION_LOOKUP: Dict[str, str] = {}
for company in COMPANIES:
    industry_norm = _normalize(company["industry"])
    location_norm = _normalize(company["location"])
    _INDUSTRY_LOOKUP.setdefault(industry_norm, company["industry"])
    _LOCATION_LOOKUP.setdefault(location_norm, company["location"])


def _extract_filters(message: str) -> Dict[str, str]:
    normalized_message = _normalize(message)
    industry = ""
    location = ""

    for norm, original in _INDUSTRY_LOOKUP.items():
        if norm and norm in normalized_message:
            industry = original
            break

    for norm, original in _LOCATION_LOOKUP.items():
        if norm and norm in normalized_message:
            location = original
            break

    return {"industry": industry, "location": location}


_COMPANY_NAME_INDEX: List[Tuple[str, dict]] = [
    (_normalize(company["name"]), company) for company in COMPANIES
]


def _find_company_matches(message: str, max_matches: int = 5) -> List[dict]:
    normalized_message = _normalize(message)
    matches: List[dict] = []
    seen: set[str] = set()

    for norm_name, company in _COMPANY_NAME_INDEX:
        if norm_name and norm_name in normalized_message:
            matches.append(company)
            seen.add(company["slug"])
            if len(matches) >= max_matches:
                return matches

    name_keys = [entry[0] for entry in _COMPANY_NAME_INDEX if entry[0]]
    close_matches = difflib.get_close_matches(
        normalized_message, name_keys, n=max_matches, cutoff=0.45
    )
    for norm_name in close_matches:
        for stored_name, company in _COMPANY_NAME_INDEX:
            if stored_name == norm_name and company["slug"] not in seen:
                matches.append(company)
                seen.add(company["slug"])
                break
        if len(matches) >= max_matches:
            return matches

    words = normalized_message.split()
    for norm_name, company in _COMPANY_NAME_INDEX:
        if company["slug"] in seen or not norm_name:
            continue
        name_tokens = norm_name.split()
        if name_tokens and any(token in words for token in name_tokens):
            matches.append(company)
            seen.add(company["slug"])
            if len(matches) >= max_matches:
                break

    return matches


def _compute_company_metrics(companies: List[dict]) -> Dict[str, Dict[str, float]]:
    """Calcula promedio y total de reseñas combinando datos de usuarios y mock."""
    slugs = [company["slug"] for company in companies]
    aggregates = (
        CompanyComment.objects.filter(company_slug__in=slugs)
        .values("company_slug")
        .annotate(
            user_review_count=Count("id"),
            user_rating_sum=Sum("rating"),
        )
    )
    aggregate_map: Dict[str, Dict[str, float]] = {
        row["company_slug"]: {
            "user_review_count": row["user_review_count"],
            "user_rating_sum": row["user_rating_sum"] or 0,
        }
        for row in aggregates
    }

    metrics: Dict[str, Dict[str, float]] = {}
    for company in companies:
        slug = company["slug"]
        aggregate = aggregate_map.get(slug, {"user_review_count": 0, "user_rating_sum": 0})
        user_count = aggregate["user_review_count"] or 0
        user_sum = aggregate["user_rating_sum"] or 0

        mock_ratings = [comment.get("rating") for comment in company.get("recent_comments", []) if comment.get("rating")]
        mock_count = len(mock_ratings)
        mock_sum = sum(mock_ratings)

        total_count = user_count + mock_count
        if total_count:
            combined_avg = round((user_sum + mock_sum) / total_count, 1)
            combined_count = total_count
        else:
            combined_avg = company["avg_rating"]
            combined_count = company["review_count"]

        metrics[slug] = {
            "avg_rating": combined_avg,
            "review_count": combined_count,
        }

    return metrics


def _merge_metrics(company: dict, metrics: Dict[str, Dict[str, float]]) -> dict:
    data = metrics.get(company["slug"], {})
    return {
        **company,
        "avg_rating": data.get("avg_rating", company["avg_rating"]),
        "review_count": data.get("review_count", company["review_count"]),
    }


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
        "author": comment.get("author", "Anónimo"),
        "quote": comment.get("quote", ""),
        "rating": comment.get("rating", 0),
        "responses_label": f"{comment.get('responses', 0)} respuestas",
        "timestamp_label": comment.get("timestamp", ""),
        "sort_key": (0, 0),
        "is_user": False,
    }


def _describe_company(company: dict) -> str:
    industry = company.get("industry", "").lower()
    location = company.get("location", "")
    summary = company.get("summary_line", "").rstrip(".")
    highlight = company.get("highlight", "").rstrip(".")

    parts: List[str] = []
    if industry and location:
        parts.append(f"{company['name']} opera en {location} dentro del sector {industry}.")
    elif industry:
        parts.append(f"{company['name']} participa en el sector {industry}.")
    elif location:
        parts.append(f"{company['name']} tiene operaciones principales en {location}.")

    if summary:
        parts.append(f"Su enfoque actual: {summary.lower()}.")
    if highlight:
        parts.append(highlight)

    if not parts:
        return f"{company['name']} impulsa iniciativas de experiencia de talento."

    return " ".join(parts)


def _candidate_qualities(company: dict) -> List[str]:
    industry = company.get("industry", "")
    location = company.get("location", "")
    trend = company.get("trend", "")
    summary = company.get("summary_line", "").rstrip(".")
    highlight = company.get("highlight", "").rstrip(".")

    traits_by_industry = {
        "Tecnologia": [
            "Dominio de metodologías ágiles y entrega continua",
            "Curiosidad técnica para experimentar y documentar aprendizajes",
        ],
        "Medios": [
            "Sensibilidad editorial para traducir hallazgos en historias",
            "Capacidad de coordinar equipos remotos en tiempos cortos",
        ],
        "Salud": [
            "Criterio ético para trabajar con datos sensibles",
            "Experiencia en procesos regulados y documentación clara",
        ],
        "Retail": [
            "Orientación comercial para activar campañas omnicanal",
            "Capacidad de lectura de métricas en tiempo real",
        ],
        "Educacion": [
            "Vocación pedagógica y empatía con distintos perfiles de aprendizaje",
            "Diseño de contenidos y evaluaciones basadas en datos",
        ],
        "Finanzas": [
            "Rigurosidad analítica para interpretar indicadores complejos",
            "Capacidad de gobierno de riesgo y cumplimiento normativo",
        ],
        "Manufactura": [
            "Mentalidad de mejora continua en plantas y operaciones",
            "Dominio de seguridad industrial y liderazgo en piso",
        ],
        "Movilidad": [
            "Toma de decisiones basada en datos para optimizar rutas",
            "Colaboración entre operaciones y servicio al cliente",
        ],
        "Energia": [
            "Conocimiento de eficiencia energética y sostenibilidad",
            "Gestión de stakeholders públicos y privados",
        ],
    }

    base_traits = traits_by_industry.get(industry, [
        "Comunicación clara con diferentes niveles de la organización",
        "Capacidad de priorizar iniciativas orientadas al cliente",
    ])

    traits: List[str] = []
    if base_traits:
        traits.extend(base_traits)

    if summary:
        traits.append(f"Alineación con iniciativas que buscan {summary.lower()}.")
    if highlight:
        traits.append(f"Interés genuino por proyectos donde {highlight.lower()}.")
    if location:
        traits.append(f"Disponibilidad para integrarse a equipos ubicados en {location}.")
    if trend:
        traits.append(f"Capacidad de acompañar una tendencia '{trend.lower()}' con métricas y feedback.")

    # Ensure uniqueness while preserving order
    seen = set()
    unique_traits = []
    for trait in traits:
        if trait not in seen:
            unique_traits.append(trait)
            seen.add(trait)

    return unique_traits[:5]


def _build_company_context(question: str, filters: Dict[str, str], max_companies: int = 3, list_request: bool = False) -> List[dict]:
    question_lower = question.lower()
    metrics = _compute_company_metrics(COMPANIES)

    industry_filter = filters.get("industry")
    location_filter = filters.get("location")

    filtered_companies = COMPANIES
    if industry_filter:
        filtered_companies = [company for company in filtered_companies if company["industry"] == industry_filter]
    if location_filter:
        filtered_companies = [company for company in filtered_companies if company["location"] == location_filter]

    include_all = list_request or bool(industry_filter or location_filter)

    matched: List[dict] = []
    if include_all:
        if filtered_companies:
            if max_companies >= len(filtered_companies):
                matched = [_merge_metrics(company, metrics) for company in filtered_companies]
            else:
                matched = [_merge_metrics(company, metrics) for company in filtered_companies[:max_companies]]
        else:
            matched = []
    else:
        search_space = filtered_companies if filtered_companies else COMPANIES
        for company in search_space:
            name_lower = company["name"].lower()
            slug = company["slug"]
            tags = [t.lower() for t in company.get("tags", [])]
            if name_lower in question_lower or slug in question_lower or any(tag in question_lower for tag in tags):
                matched.append(_merge_metrics(company, metrics))
            if len(matched) >= max_companies:
                break

    enriched: List[dict] = []
    fetch_comments = len(matched) <= 12
    for company in matched:
        slug = company["slug"]
        user_comments = []
        if fetch_comments:
            user_comments = list(
                CompanyComment.objects.filter(company_slug=slug)
                .order_by("-created_at")
                .values("comment", "rating")[:3]
            )
        enriched.append(
            {
                "name": company["name"],
                "slug": slug,
                "industry": company.get("industry"),
                "location": company.get("location"),
                "avg_rating": company.get("avg_rating"),
                "review_count": company.get("review_count"),
                "summary": company.get("summary_line"),
                "highlight": company.get("highlight"),
                "comments": list(user_comments),
            }
        )

    return enriched


def _format_context_for_prompt(companies: List[dict]) -> str:
    blocks = []
    for company in companies:
        lines = [
            f"Empresa: {company['name']} ({company['slug']})",
            f"Industria: {company.get('industry', 'N/D')} | Ubicación: {company.get('location', 'N/D')}",
            f"Promedio: {company.get('avg_rating', 'N/D')} / 5 con {company.get('review_count', 'N/D')} reseñas",
        ]
        if company.get("summary"):
            lines.append(f"Resumen interno: {company['summary']}")
        if company.get("highlight"):
            lines.append(f"Enfoque reciente: {company['highlight']}")
        if company["comments"]:
            comment_lines = []
            for comment in company["comments"]:
                comment_lines.append(f"- {comment['rating']} estrellas: {comment['comment'][:180]}")
            lines.append("Comentarios recientes:\n" + "\n".join(comment_lines))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def home(request):
    query = request.GET.get("q", "").strip()
    has_query = bool(query)

    total_companies = len(COMPANIES)
    metrics = _compute_company_metrics(COMPANIES)

    enriched_companies = [_merge_metrics(company, metrics) for company in COMPANIES]

    top_companies = sorted(
        enriched_companies, key=lambda c: (-c["avg_rating"], -c["review_count"])
    )[:6]

    if has_query:
        filtered = [company for company in enriched_companies if _match_company(company, query)]
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
            form_errors.append("El comentario no puede estar vacío.")

        try:
            rating_value = int(rating_raw)
        except (TypeError, ValueError):
            form_errors.append("Selecciona una calificación válida.")
            rating_value = None
        else:
            if rating_value < 1 or rating_value > 5:
                form_errors.append("La calificación debe ser entre 1 y 5 estrellas.")

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

    company_description = _describe_company(company)
    candidate_qualities = _candidate_qualities(company)

    context = {
        "company": company,
        "score_percent": score_percent,
        "industry_average": industry_average,
        "industry_size": len(industry_companies),
        "comment_filters": comment_filters,
        "selected_comment_filter": selected_filter,
        "filtered_comments": filtered_comments,
        "total_comment_count": total_comment_count,
        "comment_average": comment_average,
        "rating_distribution": rating_distribution,
        "form_errors": form_errors,
        "has_user_comments": bool(user_comments),
        "company_description": company_description,
        "candidate_qualities": candidate_qualities,
    }

    return render(request, "calificaciones.html", context)


def help_center(request):
    return render(request, "ayuda.html")


@require_POST
def chatbot_reply(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "No pudimos leer tu mensaje."}, status=400)

    message = payload.get("message", "").strip()
    if not message:
        return JsonResponse({"error": "Escribe una pregunta para continuar."}, status=400)

    message_lower = message.lower()
    list_request = (
        ("todas" in message_lower and "empresa" in message_lower)
        or ("lista" in message_lower and "empresa" in message_lower)
        or ("nombres" in message_lower and "empresa" in message_lower)
    )
    filters = _extract_filters(message)
    has_filters = any(filters.values())
    if list_request:
        max_context_companies = len(COMPANIES)
    elif has_filters:
        max_context_companies = 12
    else:
        max_context_companies = 3

    companies = _build_company_context(message, filters, max_companies=max_context_companies, list_request=list_request or has_filters)
    context_block = _format_context_for_prompt(companies)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        reply_text = _generate_local_answer(message, companies, filters)
        return JsonResponse({"reply": reply_text, "companies": companies})

    system_prompt = (
        "Eres el asistente de UX Manager. Responde con tono cercano y empático, pero siempre conciso. "
        "Usa únicamente la información proporcionada en el contexto para responder sobre empresas, calificaciones y reseñas. "
        "No inventes datos, no hagas suposiciones y responde solo a lo que la persona solicita. "
        "Si falta información, indica de forma amable qué acciones puede realizar en la plataforma para encontrarla.\n\n"
        f"Contexto disponible:\n{context_block}"
    )

    request_payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "temperature": 0.3,
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=20,

        )
        print(response)
        response.raise_for_status()
    except requests.RequestException as exc:
        return JsonResponse(
            {"error": f"No fue posible contactar al asistente: {exc}"},
            status=502,
        )

    completion = response.json()
    try:
        answer = completion["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return JsonResponse({"error": "La respuesta del asistente no tiene el formato esperado."}, status=502)

    return JsonResponse(
        {
            "reply": answer,
            "companies": companies,
        }
    )


def _generate_local_answer(message: str, companies: List[dict], filters: Dict[str, str]) -> str:
    total_companies = len(COMPANIES)
    message_lower = message.lower()
    global_metrics = _compute_company_metrics(COMPANIES)
    industry_filter = filters.get("industry")
    location_filter = filters.get("location")

    if "cuántas" in message_lower or "cuantas" in message_lower:
        if "empresa" in message_lower:
            return (
                f"Actualmente tenemos {total_companies} empresas registradas en la plataforma. "
                "Puedes explorar el buscador para filtrar por industria o ubicación, "
                "y entrar a cada perfil para ver reseñas detalladas."
            )

    greeting_keywords = {"hola", "hey", "buenas", "saludos", "qué tal", "como estas", "cómo estás", "que mas", "como va", "buen día", "buen dia"}
    if any(keyword in message_lower for keyword in greeting_keywords) and len(message_lower.split()) <= 7:
        return (
            "¡Hola! Soy el asistente de UX Manager. "
            "Cuéntame qué tipo de empresa buscas o qué duda tienes y te ayudo con datos."
        )

    if "mejor" in message_lower or "top" in message_lower:
        top_companies = sorted(
            [_merge_metrics(company, global_metrics) for company in COMPANIES],
            key=lambda c: (-c["avg_rating"], -c["review_count"]),
        )[:3]
        lines = [f"{idx+1}. {company['name']} - {company['avg_rating']} / 5 con {company['review_count']} reseñas"
                 for idx, company in enumerate(top_companies)]
        return (
            "Las empresas con mejor evaluación promedio son:\n"
            + "\n".join(lines)
            + "\nRevisa el ranking para aplicar filtros por industria o ubicación."
        )

    if not companies:
        if industry_filter or location_filter:
            industry_text = industry_filter or "cualquier industria"
            location_text = location_filter or "cualquier ubicacion"
            return (
                f"No encontramos empresas de {industry_text} en {location_text}. "
                "Verifica la consulta o ajusta los filtros en el buscador."
            )
        return (
            "No encontre datos especificos para responder. "
            "Menciona un nombre de empresa o agrega industria y ubicacion para afinar la busqueda."
        )

    ask_for_single = (
        ("una" in message_lower or "solo" in message_lower)
        and any(keyword in message_lower for keyword in ["elige", "elegir", "quedaria", "cual", "recomienda", "recomiendas"])
    )

    if companies:
        ranked_companies = sorted(
            companies,
            key=lambda c: (
                -global_metrics.get(c["slug"], {}).get("avg_rating", c.get("avg_rating", 0)),
                -global_metrics.get(c["slug"], {}).get("review_count", c.get("review_count", 0)),
            ),
        )

        if ask_for_single and ranked_companies:
            chosen = ranked_companies[0]
            metrics = global_metrics.get(chosen["slug"], {})
            avg = metrics.get("avg_rating", chosen.get("avg_rating", "N/D"))
            count = metrics.get("review_count", chosen.get("review_count", "N/D"))
            reason = chosen.get("highlight") or chosen.get("summary") or "recibe comentarios consistentes"
            return (
                f"Me quedaria con {chosen['name']} ({chosen.get('industry', 'Industria N/D')} - {chosen.get('location', 'Ubicacion N/D')}). "
                f"Tiene {avg} / 5 con {count} resenas y destaca porque {reason.rstrip('.')}. "
                "Revisa su perfil para confirmar que encaja con lo que necesitas."
            )

        if industry_filter or location_filter:
            header_parts = []
            if industry_filter:
                header_parts.append(f"de la industria {industry_filter}")
            if location_filter:
                header_parts.append(f"ubicadas en {location_filter}")
            header_text = "Empresas " + " y ".join(header_parts) if header_parts else "Empresas"

            top_recommendations = ranked_companies[:3]

            if not top_recommendations:
                location_text = location_filter or "cualquier ubicacion"
                industry_text = industry_filter or "cualquier industria"
                return (
                    f"No encontramos empresas para la industria {industry_text} en {location_text}. "
                    "Revisa el buscador para verificar el nombre de la ciudad o la industria."
                )

            details = []
            for idx, company in enumerate(top_recommendations, start=1):
                metrics = global_metrics.get(company["slug"], {})
                avg = metrics.get("avg_rating", company.get("avg_rating", "N/D"))
                count = metrics.get("review_count", company.get("review_count", "N/D"))
                highlight = company.get("highlight") or company.get("summary_line") or ""
                details.append(
                    f"{idx}. {company['name']} - {avg} / 5 con {count} resenas. {highlight}"
                )

            extra_hint = ""
            if len(ranked_companies) > len(top_recommendations):
                extra_hint = "\nHay mas opciones similares; explora el ranking para ver el resto."

            return (
                f"{header_text}. Aqui tienes tres recomendaciones:\n"
                + "\n".join(details)
                + extra_hint
            )
        if (
            ("todas" in message_lower and "empresa" in message_lower)
            or ("lista" in message_lower and "empresa" in message_lower)
            or ("nombres" in message_lower and "empresa" in message_lower)
        ):
            details = []
            for idx, company in enumerate(companies, start=1):
                metrics = global_metrics.get(company["slug"], {})
                avg = metrics.get("avg_rating", company.get("avg_rating", "N/D"))
                count = metrics.get("review_count", company.get("review_count", "N/D"))
                details.append(
                    f"{idx}. {company['name']} - {company.get('industry', 'Industria N/D')} - {company.get('location', 'Ubicación N/D')} - {avg} / 5 - {count} reseñas"
                )
            return (
                "Lista completa de empresas registradas en UX Manager:\n"
                + "\n".join(details)
                + "\nPara profundizar entra al perfil de cada empresa desde el buscador."
            )

        summaries = []
        for company in companies:
            snippet = (
                f"{company['name']} ({company.get('industry', 'Industria N/D')} - {company.get('location', 'Ubicación N/D')}) "
                f"tiene una calificación promedio de {company['avg_rating']} / 5 con {company['review_count']} reseñas. "
            )
            if company.get("highlight"):
                snippet += company["highlight"]
            elif company.get("summary"):
                snippet += company["summary"]
            comments = company.get("comments") or []
            if comments:
                first_comment = comments[0]
                comment_text = first_comment.get("comment", "")
                snippet += f" Comentario destacado: {first_comment.get('rating', 'N/D')}* - {comment_text[:160]}."
            summaries.append(snippet)
        summaries_text = "\n".join(summaries)
        return (
            "Te comparto un resumen rapido con la informacion disponible en UX Manager:\n"
            f"{summaries_text}\n"
            "Abre cada perfil para revisar resenas recientes y validar si se ajusta a lo que necesitas."
        )

    return (
        "No encontre datos especificos en el contexto disponible. "
        "Menciona el nombre de la empresa o agrega filtros en el buscador para ver detalles."
    )
