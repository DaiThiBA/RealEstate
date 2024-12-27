from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from SPARQLWrapper import SPARQLWrapper, JSON
from math import radians, sin, cos, sqrt, atan2

def fetch_data(endpoint_url, query):
    sparql = SPARQLWrapper(endpoint_url)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    return sparql.query().convert()

def calculate_distance(lat1, lon1, lat2, lon2):
    """Tính khoảng cách giữa 2 điểm dựa trên tọa độ (theo km)"""
    R = 6371  # Bán kính trái đất (km)
    
    lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    
    return distance

class ActionSearchRealEstate(Action):
    def name(self) -> Text:
        return "action_search_real_estate"

    async def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # Lấy vị trí làm việc của người dùng
        user_lat = tracker.get_slot("work_latitude") or "10.848"
        user_lon = tracker.get_slot("work_longitude") or "106.787"

        # SPARQL endpoint URL
        endpoint_url = "http://localhost:3030/NhaTot_realestate/sparql"

        query = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX : <https://raw.githubusercontent.com/DaiThiBA/dataOWL/refs/heads/main/updated_real_estate_ontology_V3.rdf#>

        SELECT ?project ?project_id ?project_name ?short_intro ?process ?type_name 
               ?geo ?region_name ?area_name ?ward_name ?street_name ?investor_name
               (GROUP_CONCAT(DISTINCT ?facilities; separator=", ") as ?all_facilities)
               (GROUP_CONCAT(DISTINCT ?surroundings; separator=", ") as ?all_surroundings)
               ?price ?rooms ?size ?toilets ?price_million_per_m2
               (GROUP_CONCAT(DISTINCT ?images; separator=", ") as ?all_images)
        WHERE {{
            ?project rdf:type :Project .
            OPTIONAL {{ ?project :projectid ?project_id }}
            OPTIONAL {{ ?project :project_name ?project_name }}
            OPTIONAL {{ ?project :short_introduction ?short_intro }}
            OPTIONAL {{ ?project :process ?process }}
            OPTIONAL {{ ?project :type_name ?type_name }}
            OPTIONAL {{ ?project :geo ?geo }}
            
            OPTIONAL {{
                ?project :located_at ?location .
                OPTIONAL {{ ?location :region_name ?region_name }}
                OPTIONAL {{ ?location :area_name ?area_name }}
                OPTIONAL {{ ?location :ward_name ?ward_name }}
                OPTIONAL {{ ?location :street_name ?street_name }}
            }}
            
            OPTIONAL {{ ?project :facilities ?facilities }}
            OPTIONAL {{ ?project :surroundings ?surroundings }}
            
            OPTIONAL {{
                ?project :has_investor ?investor .
                OPTIONAL {{ ?investor :investor_name ?investor_name }}
            }}
            
            OPTIONAL {{
                ?real_estate :belongs_to_project ?project ;
                             rdf:type :RealEstate .
                OPTIONAL {{ ?real_estate :price ?price }}
                OPTIONAL {{ ?real_estate :rooms ?rooms }}
                OPTIONAL {{ ?real_estate :size ?size }}
                OPTIONAL {{ ?real_estate :toilets ?toilets }}
                OPTIONAL {{ ?real_estate :price_million_per_m2 ?price_million_per_m2 }}
                
                OPTIONAL {{
                    ?real_estate :has_media ?media .
                    ?media :images ?images
                }}
            }}
        }}
        GROUP BY ?project ?project_id ?project_name ?short_intro ?process ?type_name 
                 ?geo ?region_name ?area_name ?ward_name ?street_name ?investor_name
                 ?price ?rooms ?size ?toilets ?price_million_per_m2
        LIMIT 100
        """

        try:
            results = fetch_data(endpoint_url, query)
            recommendations = []

            for result in results["results"]["bindings"]:
                score = 0
                reasons = []
                
                # Tính điểm dựa trên khoảng cách
                if 'geo' in result:
                    try:
                        geo_parts = result['geo']['value'].split(',')
                        if len(geo_parts) == 2:  # Đảm bảo có đủ 2 phần tử
                            lat, lon = geo_parts
                            distance = calculate_distance(
                                float(user_lat), float(user_lon),
                                float(lat), float(lon)
                            )
                            if distance <= 5:
                                score += 1
                                reasons.append(f"🚶 Cách nơi làm việc {distance:.1f}km")
                    except (ValueError, IndexError) as e:
                        # Bỏ qua lỗi nếu không thể xử lý geo
                        continue

                # Tính điểm dựa trên tiện ích
                if 'all_facilities' in result:
                    facilities = result['all_facilities']['value'].split(', ')
                    score += len(facilities)
                    reasons.extend([f"✨ Có {facility}" for facility in facilities])

                # Tính điểm dựa trên môi trường xung quanh
                if 'all_surroundings' in result:
                    surroundings = result['all_surroundings']['value'].split(', ')
                    score += len(surroundings)
                    reasons.extend([f"🏢 Gần {surrounding}" for surrounding in surroundings])

                project_info = {
                    'project_name': result.get('project_name', {}).get('value', 'N/A'),
                    'type': result.get('type_name', {}).get('value', 'N/A'),
                    'location': f"{result.get('ward_name', {}).get('value', '')}, {result.get('area_name', {}).get('value', '')}, {result.get('region_name', {}).get('value', '')}",
                    'price': result.get('price', {}).get('value', 'N/A'),
                    'rooms': result.get('rooms', {}).get('value', 'N/A'),
                    'size': result.get('size', {}).get('value', 'N/A'),
                    'score': score,
                    'reasons': reasons
                }

                recommendations.append(project_info)

            # Sắp xếp theo điểm số
            recommendations.sort(key=lambda x: x['score'], reverse=True)

            # Tạo response
            response = "🏘️ Danh sách bất động sản được đề xuất:\n\n"
            for rec in recommendations[:5]:  # Chỉ hiển thị top 5
                response += f"🏠 {rec['project_name']} ({rec['type']})\n"
                response += f"📍 Vị trí: {rec['location']}\n"
                response += f"💰 Giá: {rec['price']} VND\n"
                response += f"🛏️ Số phòng ngủ: {rec['rooms']}\n"
                response += f"📐 Diện tích: {rec['size']}m²\n"
                response += f"📊 Điểm đánh giá: {rec['score']}\n"
                response += "📝 Lý do đề xuất:\n"
                for reason in rec['reasons']:
                    response += f"  {reason}\n"
                response += "\n"

            if not recommendations:
                response = "❌ Không tìm thấy bất động sản nào phù hợp với yêu cầu của bạn."

            dispatcher.utter_message(text=response)

        except Exception as e:
            dispatcher.utter_message(text=f"❌ Lỗi khi truy vấn dữ liệu bất động sản: {e}")

        return []
