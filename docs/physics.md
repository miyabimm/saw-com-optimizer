# Physics and numerical conventions (implemented prototype)

This page records the equations and conventions implemented in
`src/sawopt/physics/` and the still-legacy metric/evaluation helpers. It does
not certify the placeholder COM inputs as a real device model. Scientific
equations, units, terminations, or evaluation conditions must not be changed
under a structural refactor without a reviewed scientific decision.

## COM section equations

The implementation uses the `exp(+jωt)` phasor convention, x increasing from
left to right, peak electrical voltage `V`, and terminal current `I` directed
into the transducer. `R` and `S` are forward/backward acoustic envelope
amplitudes; their normalization defines average acoustic power flux as
`|R|² − |S|²`. The implemented coupled-mode differential equations are:

```text
dR/dx = −jδ R + jκ S + jα V
dS/dx = −jκ* R + jδ S − jα* V
dI/dx = −2jα* R − 2jα S + jω C V
δ = ω/v − 2π/λ − jγ
```

Here `ω = 2πf`; `f` is Hz, `v` is m/s, `λ` and section length `L` are metres.
`δ`, `κ`, and amplitude attenuation `γ` have units m⁻¹; transduction `α`
has units √S/m; static capacitance per length `C` has units F/m. Complex
phases of `κ` and `α` enter explicitly. For a free gap, the code instead uses
`δ = ω/v − jγ`, forces `κ = α = C = 0`, and carries only free propagation and
attenuation. `γ` is amplitude loss, not power loss.

For a uniform section, define `u=(R,S)ᵀ`,

```text
A = [[−jδ,       jκ],
     [−jκ*,       jδ]]
b = (jα, −jα*)ᵀ
c = (−2jα*, −2jα)
du/dx = A u + bV
A² = (|κ|² − δ²) I
q = L sqrt(|κ|² − δ²)
```

With
`T=exp(AL)`, `F=∫₀ᴸ exp(Ax) dx`, and
`H=∫₀ᴸ (L−x) exp(Ax) dx`, the code evaluates entire functions
`sh=sinh(q)/q`, `ch=(cosh(q)−1)/q²`, and
`hh=(sinh(q)/q−1)/q²`, with Taylor series near zero, then forms

```text
T = cosh(q) I + L sh A
F = L sh I + L² ch A
H = L² ch I + L³ hh A
u(L) = T u(0) + F b V
```

Integrating the electrical current density across the finite transducer gives
`I = c F u(0) + (c H b + jω C L)V`. No inverse of `A` is used. The finite
section is represented by the P-matrix relation

```text
[S(0), R(L), I]ᵀ = P [R(0), S(L), V]ᵀ
```

The implementation eliminates `S(0)` using the second acoustic equation,
then substitutes into the outgoing-wave and integrated-current equations to
form `P`; adjacent section boundaries connect outgoing to incoming waves.
External acoustic incoming waves are zero (radiating ends). The multi-section
solver solves for all internal acoustic amplitudes in one global linear
system. Its residual check rejects nonfinite or relative residual above
`1e−8`; singular systems fail explicitly.

## COM parameter providers and assumptions

`FixedProvider` is the implemented simple parameter provider. It converts
`kappa_lambda` to `κ = (kappa_lambda/λ) exp(j phase)`, scales `α` by the square
root of aperture/reference aperture, scales `C` linearly with aperture, and
converts `loss_db_per_lambda` to amplitude attenuation
`γ = loss_db_per_lambda × ln(10)/(20 λ)`. Velocity and loss can be supplied per
region or globally. Frequency, temperature, metallization ratio, and thickness
are not interpolated. A gap has zero coupling/transduction/capacitance.

The checked-in `M0` values are hypothetical. The normalized literature profile
is an indivisible, evaluation-only profile; missing device geometry, electrode
registry, and loss details prevent claims of native-device reconstruction.
The provider rejects missing profile values rather than borrowing them from
M0. `CalibratedProvider` is a future contract only: it raises
`NotImplementedError` until validated FEM/measurement tables and interpolation
policy exist. Physical calibration is optional for the product goal, but the
current profiles remain model assumptions, not production calibration.

## COM composition and electrical interconnection

`simulate_filter` assembles a mirrored sequence of half-reflectors, gaps, and
IDTs, obtains each section's COM P matrix, connects acoustic boundaries, then
maps IDT voltages/currents into an electrical admittance. For the signed IDT
port map `B`, electrical composition follows `Yport = Bᵀ Yidt B`. The grounded
center uses `Vc=0`; a floating center is eliminated by the Schur complement
`Yee − Yec Ycc⁻¹ Yce`. Parallel DMS tracks are combined by summing their
unterminated two-port admittances before applying one source/load termination.
Hybrid resonators are independent one-port tracks connected as electrical
branches; nodal elimination uses the same Schur-complement principle.

The network uses currents directed into the two-port, peak phasors, and
independent positive real scalar source/load resistances `Rs`, `Rl`. For a
1 V-peak Thevenin open-circuit source:

```text
(Y + diag(1/Rs, 1/Rl)) V = [1/Rs, 0]ᵀ
Pavs = 1/(8 Rs)
PL = |V2|²/(2 Rl)
GT = PL/Pavs = 4 Rs |V2|²/Rl
IL = −10 log10(GT)
```

With `D=diag(√Rs,√Rl)`, `Yn = D Y D` and the implemented real-reference
scattering conversion is `S = (I+Yn)⁻¹(I−Yn)`. Under these definitions
`GT=|S21|²`. `Γin=S11`; input admittance is
`Yin=Y11−Y12 Y21/(Y22+1/Rl)` and
`Γin=(1−Rs Yin)/(1+Rs Yin)`. Output reflection follows by swapping ports.
Return loss is `−20 log10(|Γ|)` and VSWR is `(1+|Γ|)/(1−|Γ|)`; the current
reporting implementation floors the VSWR denominator at `1e−14`. No
available-power renormalization is hidden in `GT`. Complex reference
impedances are **not supported** by the evaluator; Stage 5C must establish
complex passive-port power-wave, delivered/available-power, and reflection
conventions before any such result is presented. Singular conversions/solves
fail explicitly.

## Metrics, constraint ranking, and grids

`evaluation.measure` currently records worst passband insertion loss, peak-
to-peak passband ripple, maximum input/output VSWR in band, minimum source/load
return loss in band, each stopband's minimum attenuation, and geometry
measurements plus an aggregated maximum geometry violation. It derives
normalized nonnegative violations against
the configured IL, ripple, VSWR, stopband, and geometry limits. The
illustrative B28 Rx specification is passband 758–803 MHz, IL ≤3 dB, ripple
≤2 dB, VSWR ≤2.5, with stopbands 10–700 MHz / 20 dB, 703–748 MHz / 32 dB,
832–862 MHz / 30 dB, and 880–915 MHz / 30 dB in the frozen Stage 4C config.
The same config uses max length 750 µm, max width 250 µm, minimum electrode
width/gap 0.8 µm, and max 500 electrodes. The legacy scalar geometry model
computes length as `λ(2N_io + N_center + N_ref + 2g_idt + 2g_ref)`, electrode
count as `4N_io + 2N_center + 2N_ref`, and metallization feature widths as
`λr/2` and `λ(1−r)/2`; hybrid layouts additionally account for row margins,
die dimensions, and total electrodes. Each normalized geometry violation is
`max(0, actual/limit − 1)` for upper limits or
`max(0, required/actual − 1)` for minimum feature limits. These are engineering
targets, not a production-qualified device spec. Average passband IL,
transition metrics, and group-delay ripple are roadmap metrics but are not
currently produced by this metric function.

The current scalar `feasibility_objective` is a search surrogate: feasible
records use worst IL; infeasible records receive separated scales intended to
order by maximum violation, sum violation, then IL within its stated finite
range. It is not an exact universal encoding of ranking. The reusable
`FeasibilityFirstComparator` orders feasible records by
`(feasible, worst IL, ripple, max violation, sum violation)` and infeasible
records by `(infeasible, max violation, sum violation, worst IL, ripple)`;
hybrid `GeometryFirstComparator` prefixes geometry-validity and successful vs
failed physics status before this rank. The exact tuple/API remains in
`src/sawopt/optimization/selection.py` and Q0 pins its existing comparator use.
Do not silently change these semantics; preserve individual metrics and
violations in reports.

Grid behavior is configurable, not a physics constant:

- `search_grid` uses the configured search spacing/bands plus a sparse 10–1000
  MHz broad grid (101 points). Without explicit spacing it uses deterministic
  per-band fallback samples (181 points).
- `validation_grid` defaults to a 0.25 MHz maximum step, 5,001 broad points,
  and 501 points per explicit band, with optional adaptive critical-frequency
  refinement in `problem.evaluator.dense`.
- `report_grid` is a broad plotting grid, not a substitute for search or
  validation.
- Frozen Stage 4C/Q0 comparison conditions specifically use 1,001 search
  frequencies and the common 9,113-point validation grid. The Stage 4C
  configuration records search-grid SHA-256
  `212dd2b0b71ddeffb7a8865937d132ee596870f25c989ac7d90c5dab6fd7faa0`,
  common-validation grid ID
  `2e24c4ce3f96c38baba44dc83bc60f95954a6b677cb2a37d63078e78c4cea42f`, and
  common-validation grid-content SHA-256
  `54c1daf67dd2bb9242f95e638d7bd801db536acc2c7d6f00c1f62a788bead554`.

Keep search-grid objective evaluation distinct from common/dense validation.
Do not infer a dense response from search points, change the frozen grids, or
compare candidates validated under different grid identities as if equivalent.

## Numerical checks and known limits

The analytic regression path includes: synchronous, lossless `κ=0` IDT with
real `α`, where `P13=P23=jαL` and
`P33=2α²L²+jωCL`; synchronous lossless reflector where
`P11=j tanh(κL)` and `P12=sech(κL)` for real positive `κ`; gap-only free
propagation; full augmented differential-system matrix exponential and
split-section equivalence; COM current reciprocity identities; electrical
series impedance/RLC/through limits; real-reference `GT=|S21|²`; and passive
scattering singular values. Filter admittance validation checks finiteness,
minimum Hermitian conductance eigenvalue, and reciprocity residual. The global
acoustic solve checks backward residual; optional condition-number diagnostics
are debug-only due to cost.

Taylor forms avoid cancellation near synchronism, but large `|κL|` overflow is
not stabilized by section subdivision in this prototype; configured ranges
keep values modest. These tests validate specified numerical limits, not every
possible provider or physical device.

**References and source/test traceability:** The adopted equation/sign
convention is documented in [`conventions/com_convention.md`](conventions/com_convention.md),
which cites *Automatic extraction and design of SAW resonator COM parameters
via PSO-P matrix joint optimization* and *The Extraction of Coupling-of-Modes
Parameters in a Layered Piezoelectric Substrate and Its Application to a
Double-Mode SAW Filter* (Eq. 4). These are equation references, not sources of
the hypothetical numeric parameters. Electrical definitions are also in
[`conventions/network_convention.md`](conventions/network_convention.md).
Implemented source: `src/sawopt/physics/{com,elements,network,
literature_com}.py`; the provider-visible `FilterDesign` record and decoder live
in `src/sawopt/design/space.py`, topology geometry in `src/sawopt/design/`, and
RF metrics/constraints in `src/sawopt/evaluation.py`. Regression tests include
`tests/unit/core/{test_reference,test_physics,
test_stage4a_hybrid_composition}.py`,
`tests/unit/evaluation/test_physical_composition.py`,
and `tests/unit/physics/test_import_boundaries.py`. This document transcribes
those current definitions and does not replace the code or frozen historical
study contracts.
