from __future__ import annotations

from typing import Any


def import_pandapower():
    try:
        import pandapower as pp
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError(
            "pandapower nao esta instalado. Rode scripts/instalar_dependencias_simulacao.ps1."
        ) from exc
    return pp


def create_three_bus_distribution_network(load_scale: float = 1.0) -> Any:
    pp = import_pandapower()

    net = pp.create_empty_network(name="dsse_three_bus_demo", sn_mva=1.0)
    bus_source = pp.create_bus(net, vn_kv=20.0, name="source", geodata=(0.0, 0.0))
    bus_mid = pp.create_bus(net, vn_kv=20.0, name="mid", geodata=(1.0, 0.25))
    bus_load = pp.create_bus(net, vn_kv=20.0, name="load", geodata=(2.0, 0.0))

    pp.create_ext_grid(net, bus_source, vm_pu=1.0, va_degree=0.0, name="grid")
    pp.create_line_from_parameters(
        net,
        from_bus=bus_source,
        to_bus=bus_mid,
        length_km=1.0,
        r_ohm_per_km=0.32,
        x_ohm_per_km=0.10,
        c_nf_per_km=0.0,
        max_i_ka=0.4,
        name="line_source_mid",
        geodata=[(0.0, 0.0), (1.0, 0.25)],
    )
    pp.create_line_from_parameters(
        net,
        from_bus=bus_mid,
        to_bus=bus_load,
        length_km=0.7,
        r_ohm_per_km=0.45,
        x_ohm_per_km=0.12,
        c_nf_per_km=0.0,
        max_i_ka=0.4,
        name="line_mid_load",
        geodata=[(1.0, 0.25), (2.0, 0.0)],
    )
    pp.create_load(
        net,
        bus_load,
        p_mw=0.30 * load_scale,
        q_mvar=0.12 * load_scale,
        name="load_dynamic",
    )
    return net


def solve_three_bus_distribution_network(load_scale: float = 1.0) -> dict[str, Any]:
    pp = import_pandapower()
    net = create_three_bus_distribution_network(load_scale=load_scale)
    pp.runpp(net, algorithm="nr", calculate_voltage_angles=True)

    return {
        "engine": "pandapower",
        "converged": bool(net.converged),
        "bus_vm_pu": [float(value) for value in net.res_bus.vm_pu.to_list()],
        "bus_va_degree": [float(value) for value in net.res_bus.va_degree.to_list()],
        "line_loading_percent": [float(value) for value in net.res_line.loading_percent.to_list()],
        "net": net,
    }


if __name__ == "__main__":
    result = solve_three_bus_distribution_network()
    printable = {key: value for key, value in result.items() if key != "net"}
    print(printable)
