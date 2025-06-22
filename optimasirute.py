import matplotlib.pyplot as plt
import random
import os
import math
from geopy.distance import geodesic
import firebase_admin
from firebase_admin import credentials, db

# --- Konfigurasi Lokasi ---
LOCATIONS = {
    "DEPO": (-6.890682913380755, 107.62539534137673),
    "TPS_DAGO": (-6.883993, 107.613144),
    "TPS_CIHAMPELAS": (-6.893537, 107.604953),
    "TPS_BUAHBATU": (-6.950251, 107.634587),
    "TPS_KOPO": (-6.948347, 107.573116),
    "TPS_ANTAPANI": (-6.903444, 107.660000),
    "TPS_GEDEBAGE": (-6.950000, 107.700000),
    "TPS_CIBADUYUT": (-6.978889, 107.589722),
    "TPS_KIARACONDONG": (-6.927222, 107.646944),
    "TPS_CICADAS": (-6.903889, 107.646389),
    "TPS_CICAHEUM": (-6.900000, 107.660000),
    "TPA_SARIMUKTI": (-6.800449378428952, 107.34929092078416)
}

# --- Constants ---
TPA_NAME = "TPA_SARIMUKTI"
DEPOT_NAME = "DEPO"
POPULATION_SIZE = 100
GENERATIONS = 300
CROSSOVER_RATE = 0.85
MUTATION_RATE = 0.05
ELITISM_COUNT = 2

def calculate_distance(point1_coords, point2_coords):
    """Calculate distance between two points"""
    return geodesic(point1_coords, point2_coords).km

def create_distance_matrix(coords_list):
    """Create distance matrix for all locations"""
    num_locations = len(coords_list)
    matrix = [[0.0] * num_locations for _ in range(num_locations)]
    for i in range(num_locations):
        for j in range(i, num_locations):
            dist = calculate_distance(coords_list[i], coords_list[j])
            matrix[i][j] = dist
            matrix[j][i] = dist
    return matrix

def calculate_segment_metrics(from_point, to_point, consider_traffic=False, traffic_conditions=None):
    """Calculate metrics for a route segment"""
    base_distance = calculate_distance(LOCATIONS[from_point], LOCATIONS[to_point])
    
    # Calculate duration (base: 30 km/h average speed)
    duration_minutes = base_distance * 2
    
    # Apply traffic factor
    traffic_level = "Light"
    if consider_traffic and traffic_conditions:
        traffic_level = traffic_conditions.get(f"{from_point}-{to_point}", "Light")
        traffic_factor = 1.5 if traffic_level == "Heavy" else 1.2 if traffic_level == "Moderate" else 1.0
        duration_minutes *= traffic_factor
    
    return {
        "from": from_point,
        "to": to_point,
        "distance_km": round(base_distance, 1),
        "traffic_level": traffic_level,
        "estimated_time_minutes": round(duration_minutes, 1)
    }

def calculate_route_metrics(route_points, consider_traffic=False, traffic_conditions=None):
    """Calculate metrics for entire route"""
    total_distance = 0
    total_duration = 0
    route_segments = []
    
    for i in range(len(route_points) - 1):
        from_point = route_points[i]
        to_point = route_points[i + 1]
        base_distance = calculate_distance(LOCATIONS[from_point], LOCATIONS[to_point])
        
        # Calculate segment duration
        segment_duration = base_distance * 2  # Base time: Assuming average speed of 30 km/h
        traffic_level = "Light"
        if consider_traffic and traffic_conditions:
            traffic_level = traffic_conditions.get(f"{from_point}-{to_point}", "Light")
            traffic_factor = 1.5 if traffic_level == "Heavy" else 1.2 if traffic_level == "Moderate" else 1.0
            segment_duration *= traffic_factor
            
        route_segments.append({
            "from": from_point,
            "to": to_point,
            "distance_km": round(base_distance, 1),
            "traffic_level": traffic_level,
            "estimated_time_minutes": round(segment_duration, 1)
        })
        
        total_duration += segment_duration
        total_distance += base_distance
    
    return route_segments, round(total_distance, 1), round(total_duration, 1)

def genetic_algorithm(tps_status, consider_traffic=False, traffic_conditions=None):
    """Run genetic algorithm for route optimization"""
    # Get full TPS list
    tps_full = [tps_id for tps_id, is_full in tps_status.items() if is_full and tps_id.startswith("TPS_")]
    if not tps_full:
        return [], 0, 0
    
    # Create route points and distance matrix
    route_points = [DEPOT_NAME] + tps_full + [TPA_NAME]
    coords = [LOCATIONS[point] for point in route_points]
    distance_matrix = create_distance_matrix(coords)
    
    # Initialize population with random routes (excluding DEPO and TPA)
    population = []
    for _ in range(POPULATION_SIZE):
        route = list(range(1, len(tps_full) + 1))  # Indices of TPS points
        random.shuffle(route)
        population.append(route)
    
    best_route = None
    best_distance = float('inf')
    best_duration = 0
    best_segments = []
    
    for generation in range(GENERATIONS):
        # Evaluate fitness
        fitness_scores = []
        for route in population:
            full_route = [0] + route + [len(route_points) - 1]  # Add DEPO and TPA
            route_names = [route_points[i] for i in full_route]
            segments, distance, duration = calculate_route_metrics(
                route_names,
                consider_traffic,
                traffic_conditions
            )
            fitness_scores.append(1.0 / distance if distance > 0 else float('inf'))
            
            if distance < best_distance:
                best_route = route
                best_distance = distance
                best_duration = duration
                best_segments = segments
        
        # Create next generation
        next_gen = []
        
        # Elitism
        elite_indices = sorted(range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True)[:ELITISM_COUNT]
        next_gen.extend([population[i][:] for i in elite_indices])
        
        # Create rest of next generation
        while len(next_gen) < POPULATION_SIZE:
            # Tournament selection
            parent1 = population[max(random.sample(range(len(population)), 5), key=lambda i: fitness_scores[i])][:]
            parent2 = population[max(random.sample(range(len(population)), 5), key=lambda i: fitness_scores[i])][:]
            
            # Crossover
            if random.random() < CROSSOVER_RATE:
                crossover_point = random.randint(1, len(parent1) - 1)
                child = parent1[:crossover_point]
                for gene in parent2:
                    if gene not in child:
                        child.append(gene)
            else:
                child = parent1[:]
            
            # Mutation
            if random.random() < MUTATION_RATE:
                i, j = random.sample(range(len(child)), 2)
                child[i], child[j] = child[j], child[i]
            
            next_gen.append(child)
        
        population = next_gen
    
    # Return best route found
    if best_route is not None:
        return best_segments, best_distance, best_duration
    
    return [], 0, 0

# Inisialisasi Firebase hanya sekali di awal program
firebase_initialized = False
def init_firebase():
    global firebase_initialized
    if not firebase_initialized:
        cred = credentials.Certificate(os.getenv('FIREBASE_KEY'))  # Ganti dengan path file service account JSON Anda
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://bluebin-c7d9e-default-rtdb.asia-southeast1.firebasedatabase.app/'
        })
        firebase_initialized = True

def push_route_to_firebase(route_coords_list):
    init_firebase()
    ref = db.reference('rute_optimasi')  # Node utama di database
    ref.push(route_coords_list)

# --- Jalankan Algoritma ---
if __name__ == "__main__":
    genetic_algorithm()
