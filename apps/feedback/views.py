from django.shortcuts import render

# Create your views here.
def ranking(request):
    from apps.feedback.models import CompanyComment
    
    # Importar COMPANIES directamente sin problemas de path
    try:
        from uxmanager.company_data import COMPANIES
    except ImportError:
        import importlib.util
        import os
        from pathlib import Path
        
        # Cargar company_data.py manualmente
        base_dir = Path(__file__).resolve().parent.parent.parent
        company_data_path = base_dir / 'uxmanager' / 'company_data.py'
        spec = importlib.util.spec_from_file_location("company_data", company_data_path)
        company_data = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(company_data)
        COMPANIES = company_data.COMPANIES
    
    # Obtener parámetros de filtro
    industry_filter = request.GET.get('industry', '')
    location_filter = request.GET.get('location', '')
    order_filter = request.GET.get('order', 'best')
    
    # Calcular rating promedio real para cada empresa
    companies_with_ratings = []
    
    for company in COMPANIES:
        # Obtener comentarios reales de usuarios
        user_comments = CompanyComment.objects.filter(company_slug=company['slug'])
        user_ratings = list(user_comments.values_list('rating', flat=True))
        
        # Combinar con ratings mock
        mock_ratings = [c['rating'] for c in company.get('recent_comments', [])]
        all_ratings = user_ratings + mock_ratings
        
        # Calcular promedio real
        if all_ratings:
            avg_rating = round(sum(all_ratings) / len(all_ratings), 1)
            total_reviews = len(all_ratings)
        else:
            avg_rating = company['avg_rating']
            total_reviews = company['review_count']
        
        companies_with_ratings.append({
            **company,
            'calculated_avg_rating': avg_rating,
            'calculated_review_count': total_reviews
        })
    
    # Aplicar filtros
    filtered_companies = companies_with_ratings
    
    if industry_filter:
        filtered_companies = [c for c in filtered_companies if c['industry'] == industry_filter]
    
    if location_filter:
        filtered_companies = [c for c in filtered_companies if c['location'] == location_filter]
    
    # Ordenar
    if order_filter == 'worst':
        filtered_companies = sorted(
            filtered_companies,
            key=lambda c: (c['calculated_avg_rating'], -c['calculated_review_count'])
        )[:10]
    else:
        filtered_companies = sorted(
            filtered_companies,
            key=lambda c: (-c['calculated_avg_rating'], -c['calculated_review_count'])
        )[:10]
    
    # Obtener listas únicas para filtros
    all_industries = sorted(set(c['industry'] for c in COMPANIES))
    all_locations = sorted(set(c['location'] for c in COMPANIES))
    
    context = {
        'ranked_companies': filtered_companies,
        'all_industries': all_industries,
        'all_locations': all_locations,
        'selected_industry': industry_filter,
        'selected_location': location_filter,
        'selected_order': order_filter,
        'total_results': len(filtered_companies),
    }
    
    return render(request, 'ranking.html', context)
