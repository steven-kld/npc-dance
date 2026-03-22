import requests

inputs = [
    "Андрей Петров, улица Пушкина дом 16, 4500, DEUTDEFFXXX, COBADEFFXXX, DE89 3704 0044 0532 0130 00",
    "Андрей Петров, Пушкина 16, 1000, COBADEFFXXX, DE89 3704 0044 0532 0130 00",
    "Степан Себастьян Иоанович Петровский Корсаков, Пушкина 16, 1000, COBADEFFXXX, DE89 3704 0044 0532 0130 00",
]

for i, user_input in enumerate(inputs, 1):
    print(f"\n[{i}] {user_input}")
    response = requests.post(
        "http://localhost:8000/run-flow",
        json={"input": user_input},
    )
    print(f"    {response.status_code} {response.json()}")
