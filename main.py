from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
from datetime import datetime
import uvicorn
from optimasirute import LOCATIONS, calculate_distance, genetic_algorithm
from dotenv import load_dotenv
import os
import firebase_admin
from firebase_admin import credentials, db

app = FastAPI(
    title="Route Optimization API",
    description="""
    API untuk optimasi rute pengangkutan sampah dengan mempertimbangkan kondisi lalu lintas real-time.
    
    ## Features
    * Optimasi rute berdasarkan status TPS (penuh/kosong)
    * Integrasi dengan Google Maps untuk data lalu lintas real-time
    * Perhitungan estimasi waktu tempuh
    * Visualisasi kondisi lalu lintas pada rute
    
    ## Cara Penggunaan
    1. Kirim request POST ke endpoint `/optimize-route`
    2. Sertakan status TPS dalam body request
    3. Tentukan apakah ingin mempertimbangkan lalu lintas
    4. Terima response berupa rute optimal
    
    ## Levels Lalu Lintas
    * Light: Normal
    * Moderate: Agak macet (20-50% lebih lama)
    * Heavy: Macet (>50% lebih lama)
    """,
    version="1.0.0",
    contact={
        "name": "BlueBin Development Team",
        "url": "https://github.com/bluebin",
        "email": "afif123bob@gmail.com",
    },
    openapi_tags=[{
        "name": "Route Optimization",
        "description": "Endpoints untuk optimasi rute pengangkutan sampah"
    }]
)

# Load environment variables
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Firebase initialization
cred = credentials.Certificate('bluebin-c7d9e-firebase-adminsdk-fbsvc-e5fcdc5d99.json')  # Ganti dengan path file service account JSON Anda
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bluebin-c7d9e-default-rtdb.asia-southeast1.firebasedatabase.app/'
})


class TPSStatus(BaseModel):
    """
    Status TPS (Tempat Pembuangan Sampah)
    """
    tps_id: str = "TPS_DAGO"
    is_full: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "tps_id": "TPS_DAGO",
                "is_full": True
            }
        }
    }

class OptimizationRequest(BaseModel):
    """
    Request untuk optimasi rute
    """
    tps_status: List[TPSStatus] = []
    consider_traffic: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "tps_status": [
                    {"tps_id": "TPS_DAGO", "is_full": True},
                    {"tps_id": "TPS_CIHAMPELAS", "is_full": True},
                    {"tps_id": "TPS_BUAHBATU", "is_full": False}
                ],
                "consider_traffic": True
            }
        }
    }

class RouteResponse(BaseModel):
    """
    Response hasil optimasi rute
    """
    route: List[Dict] = []
    total_distance: float = 0.0
    estimated_duration: float = 0.0
    traffic_conditions: Dict[str, str] = {}
    route_id: Optional[str] = None  # ID rute di Firebase

    model_config = {
        "json_schema_extra": {
            "example": {
                "route": [
                    {
                        "from": "DEPO",
                        "to": "TPS_DAGO",
                        "distance_km": 5.2,
                        "traffic_level": "Moderate",
                        "estimated_time_minutes": 15.5
                    },
                    {
                        "from": "TPS_DAGO",
                        "to": "TPS_CIHAMPELAS",
                        "distance_km": 3.8,
                        "traffic_level": "Light",
                        "estimated_time_minutes": 10.2
                    },
                    {
                        "from": "TPS_CIHAMPELAS",
                        "to": "TPA_SARIMUKTI",
                        "distance_km": 15.6,
                        "traffic_level": "Heavy",
                        "estimated_time_minutes": 19.8
                    }
                ],
                "total_distance": 24.6,
                "estimated_duration": 45.5,
                "traffic_conditions": {
                    "DEPO-TPS_DAGO": "Moderate",
                    "TPS_DAGO-TPS_CIHAMPELAS": "Light",
                    "TPS_CIHAMPELAS-TPA_SARIMUKTI": "Heavy"
                }
            }
        }
    }

def get_traffic_data(origin, destination):
    """
    Get real-time traffic data using Google Maps Distance Matrix API
    
    Args:
        origin (tuple): Koordinat (latitude, longitude) titik asal
        destination (tuple): Koordinat (latitude, longitude) titik tujuan
    
    Returns:
        dict: Dictionary berisi informasi lalu lintas:
            - duration: Waktu tempuh dalam detik
            - traffic_factor: Faktor kemacetan (>1 berarti lebih lambat dari normal)
            - traffic_level: Status lalu lintas ("Light", "Moderate", "Heavy", atau "Unknown")
    
    Example:
        >>> origin = (-6.914744, 107.609810)  # DEPO
        >>> destination = (-6.883993, 107.613144)  # TPS_DAGO
        >>> traffic_info = get_traffic_data(origin, destination)
        >>> print(traffic_info)
        {
            "duration": 1200,
            "traffic_factor": 1.3,
            "traffic_level": "Moderate"
        }
    """
    try:
        if not GOOGLE_MAPS_API_KEY:
            print("Google Maps API key not found")
            return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

        base_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{destination[0]},{destination[1]}",
            "departure_time": "now",
            "key": GOOGLE_MAPS_API_KEY
        }
        
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            print(f"Error from Google Maps API: Status code {response.status_code}")
            return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

        data = response.json()
        
        if data.get("status") != "OK":
            print(f"Google Maps API error: {data.get('status')}")
            return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

        if not data.get("rows") or not data["rows"][0].get("elements"):
            print("No route data received from Google Maps API")
            return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            print(f"Route error: {element.get('status')}")
            return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

        duration_in_traffic = element.get("duration_in_traffic", {}).get("value", 0)
        base_duration = element.get("duration", {}).get("value", 0)
        
        # Calculate traffic factor (how much slower than normal)
        traffic_factor = duration_in_traffic / base_duration if base_duration > 0 else 1
        
        return {
            "duration": duration_in_traffic,
            "traffic_factor": traffic_factor,
            "traffic_level": "Heavy" if traffic_factor > 1.5 else "Moderate" if traffic_factor > 1.2 else "Light"
        }
    except Exception as e:
        print(f"Error getting traffic data: {e}")
        return {"duration": 0, "traffic_factor": 1, "traffic_level": "Light"}

# Initialize Firebase
def init_firebase():
    """Initialize Firebase if not already initialized"""
    if not firebase_admin._apps:
        cred = credentials.Certificate('bluebin-c7d9e-firebase-adminsdk-fbsvc-e5fcdc5d99.json')
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bluebin-c7d9e-default-rtdb.asia-southeast1.firebasedatabase.app/'
        })

def save_route_to_firebase(route_data: RouteResponse) -> str:
    """Save route optimization results to Firebase"""
    try:
        init_firebase()
        ref = db.reference('routes')
        
        # Create route entry with timestamp and metadata
        route_entry = {
            'timestamp': datetime.now().isoformat(),
            'route': [dict(segment) for segment in route_data.route],
            'total_distance': route_data.total_distance,
            'estimated_duration': route_data.estimated_duration,
            'traffic_conditions': route_data.traffic_conditions
        }
        
        # Push data to Firebase
        new_route_ref = ref.push(route_entry)
        return new_route_ref.key
    except Exception as e:
        print(f"Error saving to Firebase: {e}")
        return None

@app.post(
    "/optimize-route",
    response_model=RouteResponse,
    summary="Optimasi Rute Pengangkutan Sampah",
    description="""
    Endpoint untuk optimasi rute pengangkutan sampah.
    
    ## Input Parameters
    * tps_status: List status TPS (penuh/kosong)
    * consider_traffic: Boolean untuk mengaktifkan pertimbangan lalu lintas
    
    ## Proses
    1. Mengecek status setiap TPS
    2. Jika consider_traffic=true, mengambil data lalu lintas real-time
    3. Menjalankan algoritma genetika untuk optimasi
    4. Menghasilkan rute optimal
    
    ## Response
    * route: Urutan rute optimal
    * total_distance: Total jarak dalam kilometer
    * estimated_duration: Estimasi waktu tempuh dalam menit
    * traffic_conditions: Kondisi lalu lintas setiap segmen
    
    ## Error Responses
    * 500: Internal Server Error - Jika terjadi kesalahan dalam proses optimasi
    """,
    response_description="Rute optimal beserta informasi terkait",
    tags=["Route Optimization"]
)
async def optimize_route(request: OptimizationRequest):
    """
    Endpoint untuk mengoptimasi rute pengangkutan sampah
    """
    try:
        # Validate request
        if not request.tps_status:
            raise ValueError("Minimal satu TPS harus diisi")

        # Update TPS status based on request
        tps_status = {item.tps_id: item.is_full for item in request.tps_status}
        
        # Validate TPS IDs
        invalid_tps = [tps_id for tps_id in tps_status.keys() if tps_id not in LOCATIONS]
        if invalid_tps:
            raise ValueError(f"TPS ID tidak valid: {', '.join(invalid_tps)}")
        
        # Get traffic data if requested
        traffic_conditions = {}
        if request.consider_traffic:
            full_tps = [tps_id for tps_id, is_full in tps_status.items() if is_full]
            relevant_locations = ["DEPO"] + full_tps + ["TPA_SARIMUKTI"]
            
            for i, name1 in enumerate(relevant_locations):
                for name2 in relevant_locations[i+1:]:
                    traffic_data = get_traffic_data(LOCATIONS[name1], LOCATIONS[name2])
                    traffic_conditions[f"{name1}-{name2}"] = traffic_data["traffic_level"]
                    traffic_conditions[f"{name2}-{name1}"] = traffic_data["traffic_level"]

        # Run optimization algorithm with traffic consideration
        route, total_distance, duration = genetic_algorithm(
            tps_status=tps_status,
            consider_traffic=request.consider_traffic,
            traffic_conditions=traffic_conditions
        )

        if not route:
            raise ValueError("Tidak ada TPS yang perlu dikunjungi atau tidak dapat menemukan rute yang valid")

        # Save route to Firebase
        save_route_to_firebase(RouteResponse(
            route=route,
            total_distance=total_distance,
            estimated_duration=duration,
            traffic_conditions=traffic_conditions
        ))        # Create response object
        route_response = RouteResponse(
            route=route,
            total_distance=total_distance,
            estimated_duration=duration,
            traffic_conditions=traffic_conditions
        )

        # Save to Firebase and get route_id
        route_id = save_route_to_firebase(route_response)
        route_response.route_id = route_id

        return route_response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)