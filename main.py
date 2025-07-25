from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Tuple, List
from geopy.distance import geodesic
import random

app = FastAPI()

# Lokasi tetap
STATIC_LOCATIONS = {
    "DEPO": (-6.94898612340884, 107.6878271549783),
    "TPA_SARIMUKTI": (-6.800449378428952, 107.34929092078416)
}

# Konstanta algoritma genetika
POPULATION_SIZE = 100
GENERATIONS = 300
CROSSOVER_RATE = 0.85
MUTATION_RATE = 0.05
ELITISM_COUNT = 2

# --- Data Model ---
class TPSItem(BaseModel):
    name: str
    lat: float
    lng: float

class TPSRequest(BaseModel):
    tps: List[TPSItem]

# --- Algoritma dan Utilitas ---
def calculate_distance(coord1, coord2):
    return geodesic(coord1, coord2).km

def calculate_route_metrics(route_points, locations_dict):
    total_distance = 0
    total_duration = 0
    route_segments = []

    for i in range(len(route_points) - 1):
        from_point = route_points[i]
        to_point = route_points[i + 1]
        base_distance = calculate_distance(locations_dict[from_point], locations_dict[to_point])
        duration = base_distance * 2  # Asumsi 30 km/h

        route_segments.append({
            "from": from_point,
            "to": to_point,
            "distance_km": round(base_distance, 1),
            "estimated_time_minutes": round(duration, 1)
        })

        total_distance += base_distance
        total_duration += duration

    return route_segments, round(total_distance, 1), round(total_duration, 1)

def genetic_algorithm(tps_dict):
    if not tps_dict:
        return [], 0, 0

    locations_dict = {**STATIC_LOCATIONS, **tps_dict}
    tps_names = list(tps_dict.keys())
    route_points = ["DEPO"] + tps_names + ["TPA_SARIMUKTI"]

    population = [random.sample(range(1, len(tps_names) + 1), len(tps_names)) for _ in range(POPULATION_SIZE)]
    best_route = None
    best_distance = float('inf')
    best_segments = []
    best_duration = 0

    for _ in range(GENERATIONS):
        fitness_scores = []
        for route in population:
            full_route = [0] + route + [len(route_points) - 1]
            named_route = [route_points[i] for i in full_route]
            segments, dist, dur = calculate_route_metrics(named_route, locations_dict)
            fitness_scores.append(1.0 / dist if dist > 0 else float('inf'))

            if dist < best_distance:
                best_route = route
                best_distance = dist
                best_segments = segments
                best_duration = dur

        elite_indices = sorted(range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True)[:ELITISM_COUNT]
        next_gen = [population[i][:] for i in elite_indices]

        while len(next_gen) < POPULATION_SIZE:
            parent1 = population[random.randint(0, POPULATION_SIZE - 1)][:]
            parent2 = population[random.randint(0, POPULATION_SIZE - 1)][:]
            child = parent1[:]

            if random.random() < CROSSOVER_RATE:
                cut = random.randint(1, len(parent1) - 1)
                child = parent1[:cut] + [g for g in parent2 if g not in parent1[:cut]]

            if random.random() < MUTATION_RATE:
                i, j = random.sample(range(len(child)), 2)
                child[i], child[j] = child[j], child[i]

            next_gen.append(child)

        population = next_gen

    return best_segments, best_distance, best_duration

# --- Endpoint ---
@app.post("/optimize")
async def optimize_route(data: TPSRequest):
    if not data.tps:
        raise HTTPException(status_code=400, detail="TPS list kosong.")

    # Konversi ke dict {name: (lat, lng)}
    tps_dict = {item.name: (item.lat, item.lng) for item in data.tps}
    
    segments, total_km, total_time = genetic_algorithm(tps_dict)

    final_route_names = [segment["from"] for segment in segments]
    if segments:
        final_route_names.append(segments[-1]["to"])  # pastikan TPA_SARIMUKTI masuk

    return {
        "segments": segments,
        "total_distance_km": total_km,
        "estimated_total_minutes": total_time
    }
