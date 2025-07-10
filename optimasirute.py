import random
from geopy.distance import geodesic

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

def calculate_distance(coord1, coord2):
    return geodesic(coord1, coord2).km

def create_distance_matrix(coords_list):
    matrix = [[0.0] * len(coords_list) for _ in range(len(coords_list))]
    for i in range(len(coords_list)):
        for j in range(i + 1, len(coords_list)):
            dist = calculate_distance(coords_list[i], coords_list[j])
            matrix[i][j] = matrix[j][i] = dist
    return matrix

def calculate_route_metrics(route_points, locations_dict, consider_traffic=False, traffic_conditions=None):
    total_distance = 0
    total_duration = 0
    route_segments = []

    for i in range(len(route_points) - 1):
        from_point = route_points[i]
        to_point = route_points[i + 1]
        base_distance = calculate_distance(locations_dict[from_point], locations_dict[to_point])
        segment_duration = base_distance * 2  # asumsi 30 km/h
        traffic_level = "Light"

        if consider_traffic and traffic_conditions:
            key = f"{from_point}-{to_point}"
            traffic_level = traffic_conditions.get(key, "Light")
            if traffic_level == "Moderate":
                segment_duration *= 1.2
            elif traffic_level == "Heavy":
                segment_duration *= 1.5

        route_segments.append({
            "from": from_point,
            "to": to_point,
            "distance_km": round(base_distance, 1),
            "traffic_level": traffic_level,
            "estimated_time_minutes": round(segment_duration, 1)
        })

        total_distance += base_distance
        total_duration += segment_duration

    return route_segments, round(total_distance, 1), round(total_duration, 1)

def genetic_algorithm(tps_data, consider_traffic=False, traffic_conditions=None):
    """
    tps_data: dict { "TPS_NAME": (lat, long) }
    """
    if not tps_data:
        return [], 0, 0

    # Gabungkan lokasi tetap dan TPS dari mobile
    locations_dict = {**STATIC_LOCATIONS, **tps_data}
    tps_names = list(tps_data.keys())
    route_points = ["DEPO"] + tps_names + ["TPA_SARIMUKTI"]

    # Buat distance matrix
    coords = [locations_dict[name] for name in route_points]
    distance_matrix = create_distance_matrix(coords)

    # Inisialisasi populasi
    population = [random.sample(range(1, len(tps_names) + 1), len(tps_names)) for _ in range(POPULATION_SIZE)]
    
    best_route = None
    best_distance = float('inf')
    best_duration = 0
    best_segments = []

    for generation in range(GENERATIONS):
        fitness_scores = []
        for route in population:
            full_route = [0] + route + [len(route_points) - 1]
            named_route = [route_points[i] for i in full_route]
            segments, dist, dur = calculate_route_metrics(named_route, locations_dict, consider_traffic, traffic_conditions)
            fitness_scores.append(1.0 / dist if dist > 0 else float('inf'))

            if dist < best_distance:
                best_route = route
                best_distance = dist
                best_duration = dur
                best_segments = segments

        # Elitism
        elite_indices = sorted(range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True)[:ELITISM_COUNT]
        next_gen = [population[i][:] for i in elite_indices]

        # Crossover & Mutation
        while len(next_gen) < POPULATION_SIZE:
            parent1 = population[random.randint(0, POPULATION_SIZE - 1)][:]
            parent2 = population[random.randint(0, POPULATION_SIZE - 1)][:]
            child = parent1[:]

            if random.random() < CROSSOVER_RATE:
                cross_point = random.randint(1, len(parent1) - 1)
                child = parent1[:cross_point] + [gene for gene in parent2 if gene not in parent1[:cross_point]]

            if random.random() < MUTATION_RATE:
                i, j = random.sample(range(len(child)), 2)
                child[i], child[j] = child[j], child[i]

            next_gen.append(child)

        population = next_gen

    return best_segments, best_distance, best_duration

# --- Contoh Penggunaan ---
if __name__ == "__main__":
    # Simulasi input dari mobile apps
    tps_input = {
        "TPS_DAGO": (-6.883993, 107.613144),
        "TPS_CIHAMPELAS": (-6.893537, 107.604953),
        "TPS_BUAHBATU": (-6.950251, 107.634587),
        "TPS_KOPO": (-6.948347, 107.573116),
        "TPS_ANTAPANI": (-6.903444, 107.660000)
    }

    segments, total_km, total_time = genetic_algorithm(tps_input)
    
    print("Rute Terbaik:")
    for seg in segments:
        print(f"{seg['from']} -> {seg['to']} ({seg['distance_km']} km, {seg['estimated_time_minutes']} menit)")

    print(f"\nTotal Jarak: {total_km} km")
    print(f"Total Estimasi Waktu: {total_time} menit")
