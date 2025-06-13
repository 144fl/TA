from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
from datetime import datetime
import uvicorn
from optimasirute import LOCATIONS, calculate_distance, genetic_algorithm
from dotenv import load_dotenv
import os

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
        base_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{destination[0]},{destination[1]}",
            "departure_time": "now",
            "key": GOOGLE_MAPS_API_KEY
        }
        
        response = requests.get(base_url, params=params)
        data = response.json()
        
        if data["status"] == "OK":
            element = data["rows"][0]["elements"][0]
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
        return {"duration": 0, "traffic_factor": 1, "traffic_level": "Unknown"}

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
        # Update TPS status based on request
        tps_status = {item.tps_id: item.is_full for item in request.tps_status}
        
        # Get traffic data if requested
        traffic_conditions = {}
        if request.consider_traffic:
            for name1, coords1 in LOCATIONS.items():
                for name2, coords2 in LOCATIONS.items():
                    if name1 != name2:
                        traffic_data = get_traffic_data(coords1, coords2)
                        traffic_conditions[f"{name1}-{name2}"] = traffic_data["traffic_level"]

        # Run optimization algorithm with traffic consideration
        route, total_distance, duration = genetic_algorithm(
            tps_status=tps_status,
            consider_traffic=request.consider_traffic,
            traffic_conditions=traffic_conditions
        )

        return RouteResponse(
            route=route,
            total_distance=total_distance,
            estimated_duration=duration,
            traffic_conditions=traffic_conditions
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)