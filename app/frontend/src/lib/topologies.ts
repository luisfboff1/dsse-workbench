import type { Topology } from './types'

// NOMENCLATURA — ler antes de renomear qualquer caso.
//
// Nao existe um "IEEE 5-bus" oficial. A IEEE mantem os casos de 14, 30, 57,
// 118 e 300 barras (arquivo da University of Washington, IEEE Common Data
// Format); o de 5 barras nao esta nessa lista. O apelido "IEEE 5-bus" e usado
// na literatura para DOIS sistemas diferentes:
//
//   - Stagg & El-Abiad (1968), "Computer Methods in Power System Analysis":
//     7 linhas, impedancias 0.02+j0.06 ... 0.08+j0.24. E o classico de
//     livro-texto de fluxo de potencia e estimacao de estado. E ESTE aqui.
//   - PJM 5-bus, distribuido como `case5` no MATPOWER e no pandapower
//     (`pn.case5()`): 6 linhas, criado para ilustrar OPF/LMP. Rede DIFERENTE.
//
// Os notebooks e scripts da tese usam `pn.case5()`, ou seja o PJM. Chamar os
// dois de "IEEE 5-bus" ja causou uma investigacao inteira atribuindo a
// diferenca de geometria (K_ii 0,91 vs 0,76) ao piso de sigma, quando eram
// redes distintas -- ver docs/bugs/BUGS.md BUG-006.
//
// O 14 barras abaixo E legitimamente IEEE (sistema AEP de 1962). O 33 barras,
// quando entrar, e Baran & Wu (1989), nao IEEE.
export const DEFAULT_TOPOLOGIES: Topology[] = [
  {
    id: 'ieee-5bus',
    name: 'Stagg & El-Abiad 5-Bus',
    buses: [
      { id: 1, name: 'Gen 1',  type: 'slack', voltage: 1.06, angle: 0, pGen: 0,   qGen: 0, pLoad: 0,    qLoad: 0,    geoX: 100, geoY: 300 },
      { id: 2, name: 'Gen 2',  type: 'pv',    voltage: 1.00, angle: 0, pGen: 0.4, qGen: 0, pLoad: 0.2,  qLoad: 0.1,  qMin: -0.4, qMax: 0.5, geoX: 350, geoY: 150 },
      { id: 3, name: 'Gen 3',  type: 'pv',    voltage: 1.00, angle: 0, pGen: 0,   qGen: 0, pLoad: 0.45, qLoad: 0.15, qMin: -0.4, qMax: 0.4, geoX: 600, geoY: 150 },
      { id: 4, name: 'Load 1', type: 'pq',    voltage: 1.00, angle: 0, pGen: 0,   qGen: 0, pLoad: 0.4,  qLoad: 0.05, geoX: 450, geoY: 400 },
      { id: 5, name: 'Load 2', type: 'pq',    voltage: 1.00, angle: 0, pGen: 0,   qGen: 0, pLoad: 0.6,  qLoad: 0.1,  geoX: 750, geoY: 350 },
    ],
    lines: [
      { id: 1, from: 1, to: 2, resistance: 0.02, reactance: 0.06,  susceptance: 0.03 },
      { id: 2, from: 1, to: 3, resistance: 0.08, reactance: 0.24,  susceptance: 0.025 },
      { id: 3, from: 2, to: 3, resistance: 0.06, reactance: 0.18,  susceptance: 0.02 },
      { id: 4, from: 2, to: 4, resistance: 0.06, reactance: 0.18,  susceptance: 0.02 },
      { id: 5, from: 2, to: 5, resistance: 0.04, reactance: 0.12,  susceptance: 0.015 },
      { id: 6, from: 3, to: 4, resistance: 0.01, reactance: 0.03,  susceptance: 0.01 },
      { id: 7, from: 4, to: 5, resistance: 0.08, reactance: 0.24,  susceptance: 0.025 },
    ],
  },
  {
    id: 'ieee-14bus',
    name: 'IEEE 14-Bus',
    buses: [
      { id: 1,  name: 'Gen 1',  type: 'slack', voltage: 1.06,  angle: 0, pGen: 2.32, qGen: 0, pLoad: 0,     qLoad: 0,     geoX: 100, geoY: 300 },
      { id: 2,  name: 'Gen 2',  type: 'pv',    voltage: 1.045, angle: 0, pGen: 0.4,  qGen: 0, pLoad: 0.217, qLoad: 0.127, qMin: -0.4, qMax: 0.5, geoX: 300, geoY: 150 },
      { id: 3,  name: 'Gen 3',  type: 'pv',    voltage: 1.01,  angle: 0, pGen: 0,    qGen: 0, pLoad: 0.942, qLoad: 0.19,  qMin: 0, qMax: 0.4, geoX: 550, geoY: 200 },
      { id: 4,  name: 'Bus 4',  type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.478, qLoad: -0.039,geoX: 200, geoY: 450 },
      { id: 5,  name: 'Bus 5',  type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.076, qLoad: 0.016, geoX: 350, geoY: 350 },
      { id: 6,  name: 'Gen 6',  type: 'pv',    voltage: 1.07,  angle: 0, pGen: 0,    qGen: 0, pLoad: 0.112, qLoad: 0.075, qMin: -0.06, qMax: 0.24, geoX: 500, geoY: 450 },
      { id: 7,  name: 'Bus 7',  type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0,     qLoad: 0,     geoX: 300, geoY: 550 },
      { id: 8,  name: 'Gen 8',  type: 'pv',    voltage: 1.09,  angle: 0, pGen: 0,    qGen: 0, pLoad: 0,     qLoad: 0,     qMin: -0.06, qMax: 0.24, geoX: 450, geoY: 550 },
      { id: 9,  name: 'Bus 9',  type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.295, qLoad: 0.166, geoX: 650, geoY: 350 },
      { id: 10, name: 'Bus 10', type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.09,  qLoad: 0.058, geoX: 700, geoY: 500 },
      { id: 11, name: 'Bus 11', type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.035, qLoad: 0.018, geoX: 500, geoY: 650 },
      { id: 12, name: 'Bus 12', type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.061, qLoad: 0.016, geoX: 600, geoY: 550 },
      { id: 13, name: 'Bus 13', type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.135, qLoad: 0.058, geoX: 700, geoY: 650 },
      { id: 14, name: 'Bus 14', type: 'pq',    voltage: 1.0,   angle: 0, pGen: 0,    qGen: 0, pLoad: 0.149, qLoad: 0.05,  geoX: 800, geoY: 500 },
    ],
    lines: [
      { id: 1,  from: 1,  to: 2,  resistance: 0.01938, reactance: 0.05917, susceptance: 0.0528 },
      { id: 2,  from: 1,  to: 5,  resistance: 0.05403, reactance: 0.22304, susceptance: 0.0492 },
      { id: 3,  from: 2,  to: 3,  resistance: 0.04699, reactance: 0.19797, susceptance: 0.0438 },
      { id: 4,  from: 2,  to: 4,  resistance: 0.05811, reactance: 0.17632, susceptance: 0.034  },
      { id: 5,  from: 2,  to: 5,  resistance: 0.05695, reactance: 0.17388, susceptance: 0.0346 },
      { id: 6,  from: 3,  to: 4,  resistance: 0.06701, reactance: 0.17103, susceptance: 0.0128 },
      { id: 7,  from: 4,  to: 5,  resistance: 0.01335, reactance: 0.04211, susceptance: 0      },
      { id: 8,  from: 4,  to: 7,  resistance: 0,       reactance: 0.20912, susceptance: 0      },
      { id: 9,  from: 4,  to: 9,  resistance: 0,       reactance: 0.55618, susceptance: 0      },
      { id: 10, from: 5,  to: 6,  resistance: 0,       reactance: 0.25202, susceptance: 0      },
      { id: 11, from: 6,  to: 11, resistance: 0.09498, reactance: 0.1989,  susceptance: 0      },
      { id: 12, from: 6,  to: 12, resistance: 0.12291, reactance: 0.25581, susceptance: 0      },
      { id: 13, from: 6,  to: 13, resistance: 0.06615, reactance: 0.13027, susceptance: 0      },
      { id: 14, from: 7,  to: 8,  resistance: 0,       reactance: 0.17615, susceptance: 0      },
      { id: 15, from: 7,  to: 9,  resistance: 0,       reactance: 0.11001, susceptance: 0      },
      { id: 16, from: 9,  to: 10, resistance: 0.03181, reactance: 0.0845,  susceptance: 0      },
      { id: 17, from: 9,  to: 14, resistance: 0.12711, reactance: 0.27038, susceptance: 0      },
      { id: 18, from: 10, to: 11, resistance: 0.08205, reactance: 0.19207, susceptance: 0      },
      { id: 19, from: 12, to: 13, resistance: 0.22092, reactance: 0.19988, susceptance: 0      },
      { id: 20, from: 13, to: 14, resistance: 0.17093, reactance: 0.34802, susceptance: 0      },
    ],
  },
]
