"""Conservative duplicate prevention; similar records never merge automatically."""
from math import asin, cos, radians, sin, sqrt
from fastapi import Cookie, Depends, Query, Response
from sqlalchemy import func, select

from .db import get_db
from .geography import directory_city
from .models import Branch, CommunityRating, ManualPlace, Organization
from .search_text import normalize_search


def same_coordinates(a, lat, lng):
    if a.latitude is None or a.longitude is None or lat is None or lng is None:
        return True
    delta = sin(radians(a.latitude-lat)/2)**2 + cos(radians(lat))*cos(radians(a.latitude))*sin(radians(a.longitude-lng)/2)**2
    return 6371008.8 * 2 * asin(min(1, sqrt(delta))) <= 50


def existing_manual_place(db, name, address, city, country, latitude, longitude, google_id):
    # Both exact name and street address are required. A shared brand/city is not enough.
    for place in db.scalars(select(ManualPlace).where(ManualPlace.active.is_(True), ManualPlace.country_code == country).order_by(ManualPlace.created_at, ManualPlace.id)):
        if google_id and place.google_place_id and google_id != place.google_place_id:
            continue
        if (normalize_search(name) == normalize_search(place.name)
            and normalize_search(address) == normalize_search(place.address)
            and normalize_search(directory_city(city, country)) == normalize_search(directory_city(place.city, country))
            and same_coordinates(place, latitude, longitude)):
            return place
    return None


def register_duplicate_review(app, session_user):
    @app.get('/v1/admin/duplicate-places')
    def candidates(response: Response, q: str = Query(default='', max_length=120),
                   db=Depends(get_db), relyqo_session: str | None = Cookie(default=None)):
        session_user(relyqo_session, db, 'RELYQO_ADMIN')
        response.headers['Cache-Control'] = 'private, no-store'
        records=[]
        manual=select(ManualPlace).where(ManualPlace.active.is_(True)).order_by(ManualPlace.id)
        partners=select(Branch,Organization).join(Organization,Organization.id==Branch.organization_id).where(
            Branch.active.is_(True),Organization.profile_status.in_(['PUBLISHED','VERIFIED_PARTNER'])).order_by(Branch.id)
        if q.strip():
            manual=manual.where(ManualPlace.name.ilike('%'+q.strip().replace('%',r'\%').replace('_',r'\_')+'%',escape='\\'))
            partners=partners.where(Organization.name.ilike('%'+q.strip().replace('%',r'\%').replace('_',r'\_')+'%',escape='\\'))
        manual=list(db.scalars(manual.limit(5001)));partners=list(db.execute(partners.limit(5001)))
        limited=len(manual)>5000 or len(partners)>5000
        for place in manual[:5000]:
            records.append({'object_key':'manual:'+place.id,'name':place.name,'address':place.address,
                'city':place.city,'country':place.country_code,'google_id':place.google_place_id})
        for branch,org in partners[:5000]:
            records.append({'object_key':'relyqo:'+branch.id,'name':org.name,'address':branch.address or branch.name,
                'city':branch.city or org.city,'country':branch.country_code,'google_id':branch.google_place_id})
        groups={}
        for item in records:
            key=(normalize_search(item['name']),normalize_search(directory_city(item['city'],item['country'])),item['country'])
            groups.setdefault(key,[]).append(item)
        counts=dict(db.execute(select(CommunityRating.object_key,func.count()).where(
            CommunityRating.included.is_(True)).group_by(CommunityRating.object_key)).all())
        matches=[]
        for group in groups.values():
            if len(group)<2:
                continue
            for item in group:
                item['community_count']=counts.get(item['object_key'],0)
            matches.append({'items':group,'same_address':len({normalize_search(item['address']) for item in group})==1,
                'same_google_id':bool(group[0]['google_id']) and len({item['google_id'] for item in group})==1})
        matches.sort(key=lambda row:(not row['same_google_id'],not row['same_address'],row['items'][0]['name']))
        return {'groups':matches[:100],'truncated':limited or len(matches)>100}
