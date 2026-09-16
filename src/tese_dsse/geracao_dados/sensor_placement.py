"""Heuristicas de placement de sensores em redes pandapower.

Implementa duas politicas iniciais:

- `auto_place_sensors_transmission`: voltada para casos como IEEE 39.
  Assume que toda barra tem SCADA, e que barras com gerador alem disso tem
  PMU (refletindo investimento maior em substacoes de geracao). Trafos e
  linhas recebem SCADA P/Q em ambos os lados.
- `auto_place_sensors_distribution`: voltada para casos como IEEE 13/14.
  Subestacao (slack) recebe SCADA + PMU. Barras de carga "internas" (com
  geracao ou com varios vizinhos) recebem AMI. Barras "edge" (folhas da
  arvore radial) recebem smart meter (4x/dia).

Sao heuristicas pragmaticas, nao otimas. Servem como ponto de partida
para que cada caso de teste tenha uma config reproduzivel. Refinar com
Arturo na medida que aparecerem requisitos do projeto.
"""

from __future__ import annotations

import networkx as nx

from .measurement import SensorPlacement, SensorSpec


def _build_graph(net) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(net.bus.index)
    for line_id, row in net.line.iterrows():
        if bool(row.in_service):
            g.add_edge(int(row.from_bus), int(row.to_bus), kind="line", id=int(line_id))
    if hasattr(net, "trafo"):
        for trafo_id, row in net.trafo.iterrows():
            if bool(row.in_service):
                g.add_edge(int(row.hv_bus), int(row.lv_bus), kind="trafo", id=int(trafo_id))
    return g


def _gen_buses(net) -> set[int]:
    gens: set[int] = set()
    if hasattr(net, "gen") and len(net.gen) > 0:
        gens.update(int(b) for b in net.gen.bus)
    if hasattr(net, "ext_grid") and len(net.ext_grid) > 0:
        gens.update(int(b) for b in net.ext_grid.bus)
    return gens


def auto_place_sensors_transmission(net) -> SensorPlacement:
    """SCADA em todas as barras + linhas + trafos. PMU em barras com gerador."""

    placement = SensorPlacement()
    gens = _gen_buses(net)

    for bus in net.bus.index:
        bus_int = int(bus)
        for var in ("v_mag", "p_inj", "q_inj"):
            placement.add(
                SensorSpec(
                    sensor_class="SCADA",
                    sensor_id=f"SCADA-bus-{bus_int}-{var}",
                    location_kind="bus",
                    location_id=bus_int,
                    variable=var,  # type: ignore[arg-type]
                )
            )
        if bus_int in gens:
            for var in ("v_mag", "v_angle"):
                placement.add(
                    SensorSpec(
                        sensor_class="PMU",
                        sensor_id=f"PMU-bus-{bus_int}-{var}",
                        location_kind="bus",
                        location_id=bus_int,
                        variable=var,  # type: ignore[arg-type]
                    )
                )

    for line_id in net.line.index:
        if not bool(net.line.at[line_id, "in_service"]):
            continue
        for side in ("from", "to"):
            for var in ("p_branch", "q_branch"):
                placement.add(
                    SensorSpec(
                        sensor_class="SCADA",
                        sensor_id=f"SCADA-line-{int(line_id)}-{side}-{var}",
                        location_kind="line",
                        location_id=int(line_id),
                        side=side,  # type: ignore[arg-type]
                        variable=var,  # type: ignore[arg-type]
                    )
                )

    if hasattr(net, "trafo"):
        for trafo_id in net.trafo.index:
            if not bool(net.trafo.at[trafo_id, "in_service"]):
                continue
            for side in ("from", "to"):
                for var in ("p_branch", "q_branch"):
                    placement.add(
                        SensorSpec(
                            sensor_class="SCADA",
                            sensor_id=f"SCADA-trafo-{int(trafo_id)}-{side}-{var}",
                            location_kind="trafo",
                            location_id=int(trafo_id),
                            side=side,  # type: ignore[arg-type]
                            variable=var,  # type: ignore[arg-type]
                        )
                    )
    return placement


def auto_place_sensors_distribution(net) -> SensorPlacement:
    """SCADA na subestacao, AMI em barras intermediarias, smart meter em folhas."""

    placement = SensorPlacement()
    g = _build_graph(net)
    gens = _gen_buses(net)

    leaves = {n for n in g.nodes if g.degree[n] == 1 and n not in gens}

    for bus in net.bus.index:
        bus_int = int(bus)
        if bus_int in gens:
            sensor_class = "SCADA"
            for var in ("v_mag", "p_inj", "q_inj"):
                placement.add(
                    SensorSpec(
                        sensor_class=sensor_class,
                        sensor_id=f"SCADA-bus-{bus_int}-{var}",
                        location_kind="bus",
                        location_id=bus_int,
                        variable=var,  # type: ignore[arg-type]
                    )
                )
            for var in ("v_mag", "v_angle"):
                placement.add(
                    SensorSpec(
                        sensor_class="PMU",
                        sensor_id=f"PMU-bus-{bus_int}-{var}",
                        location_kind="bus",
                        location_id=bus_int,
                        variable=var,  # type: ignore[arg-type]
                    )
                )
            continue

        if bus_int in leaves:
            for var in ("v_mag", "p_inj", "q_inj"):
                placement.add(
                    SensorSpec(
                        sensor_class="SMART_METER",
                        sensor_id=f"SM-bus-{bus_int}-{var}",
                        location_kind="bus",
                        location_id=bus_int,
                        variable=var,  # type: ignore[arg-type]
                    )
                )
        else:
            for var in ("v_mag", "p_inj", "q_inj"):
                placement.add(
                    SensorSpec(
                        sensor_class="AMI",
                        sensor_id=f"AMI-bus-{bus_int}-{var}",
                        location_kind="bus",
                        location_id=bus_int,
                        variable=var,  # type: ignore[arg-type]
                    )
                )

    # Linhas e trafos: SCADA P/Q em ambos os lados onde houver SCADA na barra
    # adjacente.  Em DSSE pratica isso modela o fato de SCADA estar concentrado
    # na subestacao.
    for line_id in net.line.index:
        if not bool(net.line.at[line_id, "in_service"]):
            continue
        from_bus = int(net.line.at[line_id, "from_bus"])
        to_bus = int(net.line.at[line_id, "to_bus"])
        if from_bus in gens or to_bus in gens:
            for side in ("from", "to"):
                for var in ("p_branch", "q_branch"):
                    placement.add(
                        SensorSpec(
                            sensor_class="SCADA",
                            sensor_id=f"SCADA-line-{int(line_id)}-{side}-{var}",
                            location_kind="line",
                            location_id=int(line_id),
                            side=side,  # type: ignore[arg-type]
                            variable=var,  # type: ignore[arg-type]
                        )
                    )

    if hasattr(net, "trafo"):
        for trafo_id in net.trafo.index:
            if not bool(net.trafo.at[trafo_id, "in_service"]):
                continue
            for side in ("from", "to"):
                for var in ("p_branch", "q_branch"):
                    placement.add(
                        SensorSpec(
                            sensor_class="SCADA",
                            sensor_id=f"SCADA-trafo-{int(trafo_id)}-{side}-{var}",
                            location_kind="trafo",
                            location_id=int(trafo_id),
                            side=side,  # type: ignore[arg-type]
                            variable=var,  # type: ignore[arg-type]
                        )
                    )

    return placement
