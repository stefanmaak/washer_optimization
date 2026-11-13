# Washer optimization

## Run the simulation

Requires Python ≥ 3.11.

```bash
git clone https://github.com/stefanmaak/washer_optimization.git
cd washer_optimization
python3 -m venv venv
source venv/bin/activate
pip install "./interface_service[sim]"
washing_interface_service --sim
```

- Simulation GUI: http://localhost:8050
- Interface API: http://localhost:8100/docs
