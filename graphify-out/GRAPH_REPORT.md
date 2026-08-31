# Graph Report - hibrid  (2026-08-24)

## Corpus Check
- 136 files · ~231,422 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2090 nodes · 4954 edges · 171 communities (101 shown, 70 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 914 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Readiness & Baseline Comparison
- Session Generation Core
- Progression Engine
- shadcn UI Primitives
- Variation Context & Constraints
- Movement Pattern Rules
- API Output Schemas & Outcomes
- Form Input UI Primitives
- Exercise Library Tests
- Biometrics & User Enums
- Exercise Model & Library Errors
- Routine Variation
- Fitness Assessment Biometrics
- API Integration Tests
- Tab Bar & Badge UI
- Load Management
- Objective Weights & Goals
- TypeScript Config
- Training Memory Tests
- Dose & Routine Entry
- Variation Outcomes
- FastAPI App Routes
- Session Block Schemas
- Alert Dialog UI
- Health Profile & Injuries
- App Router & Routes
- Engine CLI
- Session Generation Tests
- Core Domain Models
- Dose API Schemas
- Frontend Error Capture
- components.json Config
- Frontend Fitness Mock
- API Pydantic Schemas
- Load Management Tests
- Menubar UI
- One-Rep-Max Formula
- Performed Exercise & Set History
- Performance Record Tests
- Arcade Game UI
- Frontend Engine API Client
- Session History Records
- Skill Ceiling Filtering
- Package Dependencies
- Form UI Components
- ContextFilterOut
- SessionIntent
- ObjectiveStrategy
- ExercisePerformanceRecord
- Test_Load_Management Py
- Carousel Tsx
- Account key resolves to identity
- TaperOut
- WorkloadState
- Variation_Context Py
- assess()
- VITE_API_URL
- VariationContextIn
- A fortnight of steady HRV plus one fr...
- Test_Objective_Strategy Py
- @capacitor/cli
- Chart Tsx
- LoadManagementAssessment
- HypertrophyStrategy
- MuscularEnduranceStrategy
- StrengthStrategy
- Training_Memory Py
- Variation vs progression tension
- ObjectiveOut
- Library Data Ts
- Lovable Error Reporting Ts
- Weekday
- intent_exceeds()
- Six weeks at three sessions a week --...
- DurationDoseIn
- GenerateSessionRequest
- RoundsDoseIn
- best_matches()
- Breadcrumb Tsx
- Drawer Tsx
- Navigation Menu Tsx
- Select Tsx
- LastPerformance
- scripts
- Card Tsx
- Objective_Strategy Py
- _reroll()
- Health data stays on the device
- Exception
- GeneratedSessionOut
- Package Json
- Alert Tsx
- LoadModulator
- TrainingLoadSummary
- A client has to render an intensity-p...
- Re-rolling a block drops the adaptive...
- Sonner Tsx
- @capacitor/core
- @capacitor/haptics
- @capacitor/ios
- class-variance-authority
- cmdk
- Enums are shared, never forked
- date-fns
- embla-carousel-react
- eslint
- eslint-config-prettier
- @eslint/js
- eslint-plugin-prettier
- eslint-plugin-react-refresh
- hibrid-app Lovable agents notice
- Capacitor Config Ts
- @hookform/resolvers
- input-otp
- lucide-react
- @radix-ui/react-accordion
- @radix-ui/react-alert-dialog
- @radix-ui/react-aspect-ratio
- @radix-ui/react-avatar
- @radix-ui/react-checkbox
- @radix-ui/react-collapsible
- @radix-ui/react-context-menu
- @radix-ui/react-dialog
- @radix-ui/react-dropdown-menu
- @radix-ui/react-hover-card
- @radix-ui/react-label
- @radix-ui/react-menubar
- @radix-ui/react-navigation-menu
- @radix-ui/react-popover
- @radix-ui/react-progress
- @radix-ui/react-radio-group
- @radix-ui/react-select
- @radix-ui/react-separator
- @radix-ui/react-slider
- @radix-ui/react-slot
- @radix-ui/react-switch
- @radix-ui/react-toggle
- @radix-ui/react-toggle-group
- @radix-ui/react-tooltip
- react
- react-dom
- react-hook-form
- react-resizable-panels
- sonner
- tailwindcss
- @tailwindcss/vite
- @tanstack/react-query
- @tanstack/react-router
- @tanstack/react-start
- @tanstack/router-plugin
- tw-animate-css
- vaul
- vite-tsconfig-paths
- zod
- @lovable.dev/vite-tanstack-config
- nitro
- @types/node
- @types/react
- @types/react-dom
- typescript
- typescript-eslint
- vite
- TanStack file-based routing conventions
- hibrid

## God Nodes (most connected - your core abstractions)
1. `cn()` - 231 edges
2. `VariationContext` - 114 edges
3. `Muscle` - 86 edges
4. `generate_session()` - 83 edges
5. `vary_routine()` - 79 edges
6. `ExerciseDB` - 68 edges
7. `Routine` - 52 edges
8. `User` - 51 edges
9. `RepsDose` - 50 edges
10. `RoutineEntry` - 48 edges

## Surprising Connections (you probably didn't know these)
- `The engine core stays pure` --rationale_for--> `vary_entry()`  [INFERRED]
  hibrid-engine/docs/decisions.md → hibrid-engine/src/hibrid/variation.py
- `Health data stays on the device` --rationale_for--> `VariationContext`  [INFERRED]
  hibrid-engine/docs/decisions.md → hibrid-engine/src/hibrid/variation_context.py
- `The engine core stays pure` --rationale_for--> `generate_session()`  [INFERRED]
  hibrid-engine/docs/decisions.md → hibrid-engine/src/hibrid/session_generation.py
- `The generator refuses to invent a starting load` --rationale_for--> `generate_session()`  [INFERRED]
  hibrid-engine/docs/decisions.md → hibrid-engine/src/hibrid/session_generation.py
- `Re-rolling a block drops the adaptive tier` --rationale_for--> `vary_block()`  [EXTRACTED]
  hibrid-engine/docs/decisions.md → hibrid-engine/src/hibrid/session_generation.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Adaptive variation engine invariant handling** — concept_invariant_choice, hibrid_engine_src_hibrid_variation_vary_entry, hibrid_engine_src_hibrid_objective_strategy_objectivestrategy_variation_policy, hibrid_engine_src_hibrid_objective_strategy_invariant [INFERRED 0.75]
- **Health-data-on-device privacy safeguard** — concept_health_data_on_device, concept_tiered_inputs, concept_account_key [INFERRED 0.65]

## Communities (171 total, 70 thin omitted)

### Community 0 - "Readiness & Baseline Comparison"
Cohesion: 0.06
Nodes (66): BaselineComparisonOut, One metric against its own trailing baseline, inputs included. The raw numbers…, as_utc(), BaselineComparison, _compare(), _compare_channel(), _freshest(), datetime (+58 more)

### Community 1 - "Session Generation Core"
Cohesion: 0.06
Nodes (78): The engine core stays pure, The generator refuses to invent a starting load, Muscle, Canonical muscle vocabulary. The source dataset expresses muscles as free text…, generate_session(), A way in which the generated session does not match what was asked for. Every…, Build a session for ``duration_minutes`` training ``muscles``. Difficulty is…, Re-roll one block, holding its own volume and time. This is ``vary_entry``… (+70 more)

### Community 2 - "Progression Engine"
Cohesion: 0.06
Nodes (63): ProgressionOut, What history said this entry's load should be, and why (M8b).…, _decide(), ExerciseProgression, ProgressionDecision, ProgressionPlan, Enum, str (+55 more)

### Community 3 - "shadcn UI Primitives"
Cohesion: 0.05
Nodes (56): AccordionContent, AccordionItem, AccordionTrigger, Avatar, AvatarFallback, AvatarImage, Command, CommandEmpty (+48 more)

### Community 4 - "Variation Context & Constraints"
Cohesion: 0.07
Nodes (61): Everything about one person that constrains varying one routine. A stdlib…, Everything that can only ever reduce the dose, combined. Readiness and load…, Whether a solved load is actually liftable with what they own., Resolve the V2 models that bear on variation. ``environment`` selects which…, VariationContext, bench_routine(), dumbbells_only(), illness_reported() (+53 more)

### Community 5 - "Movement Pattern Rules"
Cohesion: 0.06
Nodes (50): MovementPattern, How a movement loads the body. The classic gym patterns came first. The…, Union of every currently-binding movement-pattern contraindication., parametrize, Movement-pattern derivation rules in the importers. Every case here is a real…, The source files squats, lunges and curls together under 'Knee Dominant', which…, The recovery is scoped to the knee-dominant bucket precisely because these name…, This one shipped wrong: the exercise was labelled a vertical pull because it is… (+42 more)

### Community 6 - "API Output Schemas & Outcomes"
Cohesion: 0.06
Nodes (29): EnumT, PerformanceRecordOut, A re-rolled block, carrying the account of how it got that way., A varied entry, carrying the account of how it got that way. ``dose_outcome``…, One exercise's rolling state. Derived, never authoritative., One exercise slot, and the invariant re-rolling it must preserve. ``volume``…, RoutineEntryOut, SessionBlockOut (+21 more)

### Community 7 - "Form Input UI Primitives"
Cohesion: 0.06
Nodes (40): Input, Separator, SheetContent, SheetContentProps, SheetDescription, SheetFooter(), SheetHeader(), SheetOverlay (+32 more)

### Community 8 - "Exercise Library Tests"
Cohesion: 0.05
Nodes (33): Guards on the imported exercise library. data/exercises.yaml is generated from…, Regression: 'row' was matched as a bare substring, so 'throw down' classified a…, Jack burpee' and 'mountain climber' read as plyometric by keyword but target…, A quad stretch and a leg press share a target muscle but are not alternatives…, The point of the functional import: implements the gym-centric library had no…, A loaded carry is not a squat, a press or a pull. If these came back empty the…, Records the functional source never described carry no difficulty or plane of…, 35 exercises appear in both sources. They keep their original id -- a routine… (+25 more)

### Community 9 - "Biometrics & User Enums"
Cohesion: 0.12
Nodes (34): Dated, immutable measurement records. Every model here is one observation at…, AssessmentMethod, BiologicalSex, BodyRegion, InjuryStatus, Laterality, MeasurementSource, MenstrualPhase (+26 more)

### Community 10 - "Exercise Model & Library Errors"
Cohesion: 0.07
Nodes (33): An exercise id that is not in the library. Subclasses ``KeyError`` so existing…, UnknownExerciseError, Exercise, Target plus secondaries -- the full set this exercise trains., How interchangeable two exercises are, in ``[0.0, 1.0]``. Weighted so the…, _blocks_per_muscle(), _candidates(), _default_name() (+25 more)

### Community 11 - "Routine Variation"
Cohesion: 0.09
Nodes (39): Vary ``routine`` for one person. ``context`` is what makes the result personal…, vary_routine(), db(), fixture, parametrize, A cardio exercise carrying a rep dose is refused by the modality guard, not by…, The search deliberately stays near the current scheme, so an 8-rep entry cannot…, Schemes existed; none satisfied the tolerances. Distinct from having no schemes… (+31 more)

### Community 12 - "Fitness Assessment Biometrics"
Cohesion: 0.09
Nodes (29): BodyComposition, CardiovascularFitness, FitnessAssessment, MeasurementRecord, Subjective self-report. Kept separate from ``RecoveryReading`` because it is a…, Aerobic capacity markers, measured or estimated., The 'fitness score', decomposed by quality. A single overall number is what…, Fields common to every observation. ``source`` and ``confidence`` exist so that… (+21 more)

### Community 13 - "API Integration Tests"
Cohesion: 0.06
Nodes (14): parametrize, The whole point of the outcome field: three different reasons for "unchanged"…, The milestone test, end to end through the API., The reason this context travels in the body: extra=\"forbid\" means a…, One reading has no baseline to be suppressed against, and that must read as…, Each call is a fresh Routine (a variation gets its own routine_id per M1), so…, Reps only have to land in (1, 6) when the engine actually found a new scheme --…, test_a_single_reading_yields_no_assessment_rather_than_a_guess() (+6 more)

### Community 14 - "Tab Bar & Badge UI"
Cohesion: 0.07
Nodes (21): TabBar(), tabs, Badge(), BadgeProps, badgeVariants, Checkbox, HoverCardContent, InputOTP (+13 more)

### Community 15 - "Load Management"
Cohesion: 0.10
Nodes (26): _assess_workload(), LoadMetric, next_target_event(), datetime, Enum, str, UUID, M8c: what the last four weeks, and the next two, say about today's dose. The… (+18 more)

### Community 16 - "Objective Weights & Goals"
Cohesion: 0.08
Nodes (26): ObjectiveWeights, model_validator, A coherent training intent over a time window. A user may hold several…, A normalised preference distribution over training objectives. Weights must be…, Build from arbitrary non-negative shares, scaling them to sum to 1., TrainingGoal, Highest-priority active goal, if any. Ties break toward the earliest-listed…, goal_for() (+18 more)

### Community 17 - "TypeScript Config"
Cohesion: 0.06
Nodes (31): compilerOptions, allowImportingTsExtensions, exactOptionalPropertyTypes, jsx, lib, module, moduleResolution, noEmit (+23 more)

### Community 18 - "Training Memory Tests"
Cohesion: 0.16
Nodes (29): memory(), performed_set(), M8a: the engine finally reads what the user actually did. The claims worth…, 5x100 estimates higher than 1x110 under Epley. Taking the heaviest load would…, A formula attached to no value is as uninterpretable as the reverse., A 20kg warm-up is not evidence of anything, and counting it in volume or set…, They stay in history as the adherence signal -- which is exactly why they must…, Explaining a prescription with work done after it is target leakage. (+21 more)

### Community 19 - "Dose & Routine Entry"
Cohesion: 0.10
Nodes (23): Resistance training: sets of reps against an external (or zero) load., RepsDose, RoutineEntry, test_strength_objective_keeps_varied_entries_within_its_rep_range(), Safety is not subject to the novelty dial., When nothing legal exists the contraindicated exercise stays in the output --…, A 20kg dumbbell rack cannot deliver a volume-preserving 60kg solution., The schema names novelty_preference as the dial substitution_prob should come… (+15 more)

### Community 20 - "Variation Outcomes"
Cohesion: 0.09
Nodes (23): DoseOutcome, EntryVariation, ExerciseOutcome, pct_diff(), _prescribed_reps(), Enum, Random, str (+15 more)

### Community 21 - "FastAPI App Routes"
Cohesion: 0.16
Nodes (23): _db(), generate(), get_routine(), _load_named_routine(), FastAPI playground for the routine-variation engine. This exposes the same…, Build a session from scratch: a time budget, muscles, and a difficulty. The…, Re-roll one block, holding its own volume and time. Stateless like everything…, The strategy for an objective, or a 400. Only the three resistance objectives… (+15 more)

### Community 22 - "Session Block Schemas"
Cohesion: 0.09
Nodes (18): A block sent back for re-rolling. Only the fields the invariant is computed…, SessionBlockIn, _load_policy(), Enum, str, Which basis the session's loads came from, in aggregate. Bodyweight blocks are…, Where a block's prescribed weight came from. Kept as explicit outcomes rather…, Whether this block can be handed to the user as-is. ``NO_BASIS`` is the only… (+10 more)

### Community 23 - "Alert Dialog UI"
Cohesion: 0.12
Nodes (21): AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter(), AlertDialogHeader(), AlertDialogOverlay, AlertDialogTitle (+13 more)

### Community 24 - "Health Profile & Injuries"
Cohesion: 0.10
Nodes (20): HealthProfile, Injury, MedicalConsideration, model_validator, All safety-relevant constraints, gathered into one place. Aggregated rather…, A localised physical limitation, current or historical. Resolved injuries are…, Whether this injury should currently constrain programming., A health condition that changes what safe programming looks like. Held as free-… (+12 more)

### Community 25 - "App Router & Routes"
Cohesion: 0.13
Nodes (21): getRouter(), Route, Route, Route, Route, Route, FileRoutesByFullPath, FileRoutesById (+13 more)

### Community 26 - "Engine CLI"
Cohesion: 0.18
Nodes (17): main(), print_comparison(), Sum of each entry's own dose currency. Only physically meaningful when every…, Routine, _dump_dose(), dump_routine(), load_routine(), _parse_dose() (+9 more)

### Community 27 - "Session Generation Tests"
Cohesion: 0.09
Nodes (22): _generate(), Silently preferring one would be exactly the quietly dropped field that…, The permits() check itself is covered in test_session_generation; what this…, The default ceiling applies with no background sent and removes a third of the…, test_a_health_contraindication_narrows_the_generated_pool_over_http(), test_a_muscle_only_trained_outside_resistance_is_reported_not_dropped(), test_difficulty_moves_volume_and_holds_time_over_http(), test_difficulty_stated_twice_and_agreeing_is_allowed() (+14 more)

### Community 28 - "Core Domain Models"
Cohesion: 0.20
Nodes (16): BodyPart, Difficulty, Equipment, ForceType, Mechanics, Modality, PlaneOfMotion, Enum (+8 more)

### Community 29 - "Dose API Schemas"
Cohesion: 0.12
Nodes (12): DoseOut, DistanceDoseIn, DistanceDoseOut, _dose_out_from_domain(), DistanceDose, Dose, ABC, The prescribed quantity of work for one routine entry. Resistance training's… (+4 more)

### Community 30 - "Frontend Error Capture"
Cohesion: 0.16
Nodes (13): consumeLastCapturedError(), describeError(), describeStatus(), originalConsoleError, safeStringify(), renderErrorPage(), fetch(), getServerEntry() (+5 more)

### Community 31 - "components.json Config"
Cohesion: 0.11
Nodes (18): aliases, components, hooks, lib, ui, utils, iconLibrary, registries (+10 more)

### Community 32 - "Frontend Fitness Mock"
Cohesion: 0.19
Nodes (17): generateSession(), varyBlock(), buildSession(), calisthenicsSeeds, crossfitSeeds, currentVariant(), efforts, equipmentOptions (+9 more)

### Community 33 - "API Pydantic Schemas"
Cohesion: 0.15
Nodes (13): _ApiModel, PerformanceRecordsResponse, BaseModel, Pydantic request/response schemas for the HTTP API. The API is an external-data…, Re-roll one block of a generated session, holding its own volume and time.…, One way the generated session does not match what was asked for., RepsDoseIn, RepsDoseOut (+5 more)

### Community 34 - "Load Management Tests"
Cohesion: 0.17
Nodes (19): bench_routine(), Two tiers, so the response is proportionate. A week 40% up on the average is…, Deliberately diverging from M8a's ``PERFORMED_STATUSES``: an abandoned session…, The invisible case, arriving by M8c's route: challenging (1.15) against an…, The M8c milestone test. Accumulated load is the third thing that scales *how…, Both moved the target; the per-entry outcome names one. Being backed off for…, One logged session, sRPE by default and volume-load on request., Three sessions a week for ``weeks`` weeks, ending yesterday. (+11 more)

### Community 35 - "Menubar UI"
Cohesion: 0.12
Nodes (11): Menubar, MenubarCheckboxItem, MenubarContent, MenubarItem, MenubarLabel, MenubarRadioItem, MenubarSeparator, MenubarShortcut() (+3 more)

### Community 36 - "One-Rep-Max Formula"
Cohesion: 0.12
Nodes (15): OneRepMaxFormula, Enum, str, Estimated 1RM, or ``None`` where the formula does not apply. ``None`` covers a…, Which rep-max estimator produced a number. A closed enum rather than the…, The inverse of ``estimate``: what to load for ``reps`` reps. This is what makes…, A completed single IS a one-rep max -- there is nothing to estimate. Pinned…, The reason the schema records which estimator produced a number: a bare… (+7 more)

### Community 37 - "Performed Exercise & Set History"
Cohesion: 0.13
Nodes (13): PerformedExercise, PerformedSet, model_validator, One executed set. Load, reps, duration and distance are all optional because a…, reps x load, the standard resistance-training volume unit. Mirrors…, All sets of one exercise within a session., A user who swapped in a dumbbell press produced evidence about the dumbbell…, Same rule as readiness: an import that arrives without a timezone must not… (+5 more)

### Community 38 - "Performance Record Tests"
Cohesion: 0.18
Nodes (17): bench_history(), bench_set(), performance_records(), performed_session(), The heaviest set in the log is in a session that never happened., A bodyweight-only history still produces a record -- with a null 1RM and a…, The error that otherwise stays silent until one person's training data has been…, One recent session at a load the routine below does not know about. (+9 more)

### Community 39 - "Arcade Game UI"
Cohesion: 0.17
Nodes (12): ArcadeButton(), barColor, Chip(), Panel(), Screen(), StatBar(), Track(), avatarStats (+4 more)

### Community 40 - "Frontend Engine API Client"
Cohesion: 0.13
Nodes (13): BlockEngineState, DIFFICULTY_BY_EFFORT, EngineBlock, engineBlockToBlock(), EngineDose, FULL_BODY, GenerateResponse, MUSCLE_MAP (+5 more)

### Community 41 - "Session History Records"
Cohesion: 0.14
Nodes (10): performance_records(), Rebuild per-exercise performance records from a session log (M8a). Always…, A session log to derive per-exercise performance records from. Sessions travel…, SessionHistoryIn, Per-exercise history, resolved once and queried many times. A stdlib dataclass…, ``None`` means never performed -- which is different from performed badly, and…, What this user should be loading for ``reps`` reps, from history. Derived from…, Best estimate for this movement, or ``None`` if there isn't one. ``None`` here… (+2 more)

### Community 42 - "Skill Ceiling Filtering"
Cohesion: 0.21
Nodes (16): Whether this movement's skill demand suits the user's experience. Fails…, The hardest movement this user may be prescribed. Public because the report…, How much of the library the skill ceiling alone rules out. Worth surfacing for…, skill_ceiling_for(), summarise_skill_filter(), _within_skill_ceiling(), ExperienceLevel, Training experience, which conditions how fast progression may advance.… (+8 more)

### Community 43 - "Package Dependencies"
Cohesion: 0.13
Nodes (15): @capacitor/status-bar, clsx, dependencies, @capacitor/status-bar, clsx, @radix-ui/react-scroll-area, @radix-ui/react-tabs, react-day-picker (+7 more)

### Community 44 - "Form UI Components"
Cohesion: 0.19
Nodes (12): FormControl, FormDescription, FormFieldContext, FormFieldContextValue, FormItem, FormItemContext, FormItemContextValue, FormLabel (+4 more)

### Community 45 - "ContextFilterOut"
Cohesion: 0.16
Nodes (9): ContextFilterOut, GenerationReportOut, How much of the library the supplied context still permits., What was asked for, what came out, and every way the two differ. The part to…, What was asked for, what came out, and every way the two differ., Whether the whole session can be handed to the user as-is. False when any…, SessionGenerationReport, ContextFilterReport (+1 more)

### Community 46 - "SessionIntent"
Cohesion: 0.14
Nodes (11): ``sessions`` comes from the request's own ``history`` block rather than being…, datetime, str, What to scale the volume target by. ``MODERATE`` is exactly 1.0, so the default…, Resolve a whole ``User``. The headline of M3: V2 finally read.…, How hard the user has asked *this* session to be. A directive, not a…, SessionIntent, Harder' means more work in the same window, not a longer workout -- session… (+3 more)

### Community 47 - "ObjectiveStrategy"
Cohesion: 0.13
Nodes (7): ObjectiveStrategy, One ``TrainingObjective``'s stance on how a resistance set should be…, The modality this objective prescribes work in. Entries whose exercise doesn't…, Inclusive (min, max) reps this objective trains in. Doubles as its intensity…, Tempo: seconds per rep., Target perceived-effort band, on the standard 1-10 RPE scale., Nearby (sets, reps) schemes to try, clipped to this objective's ranges and…

### Community 48 - "ExercisePerformanceRecord"
Cohesion: 0.15
Nodes (13): ExercisePerformanceRecord, Rolling per-exercise state. DERIVED DATA. Everything here is recomputable from…, date, Elapsed years, using the average Gregorian year to stay continuous. Continuity…, Who the user is, independent of their current condition., Age on a given date. Requires the date explicitly so that any value derived…, UserProfile, _years_between() (+5 more)

### Community 49 - "Test_Load_Management Py"
Cohesion: 0.21
Nodes (14): event_in(), profile(), M8c: the block, not the session. Two claims under test. First, that a week's…, Silence would read as the feature being missing. Saying "your event is 40 days…, 0.55 x 0.75 is 0.41 -- a session neither input asked for and no coach would…, Different time scales, both real: how this body woke up, and what the last four…, A fortnight of steady HRV, then a crash on the morning being planned., suppressed_recovery() (+6 more)

### Community 50 - "Carousel Tsx"
Cohesion: 0.19
Nodes (13): Carousel, CarouselApi, CarouselContent, CarouselContext, CarouselContextProps, CarouselItem, CarouselNext, CarouselOptions (+5 more)

### Community 51 - "Account key resolves to identity"
Cohesion: 0.21
Nodes (13): Account key resolves to identity, Frontend falls back to local mock when engine unreachable, The exercise library is generated, not authored, Muscle is a closed enum; free text must never re-enter, How to write code here (CLAUDE.md), Simplicity Gate pre-implementation checklist, V1 data model and API draft, Architectural decisions and reasoning (+5 more)

### Community 52 - "TaperOut"
Cohesion: 0.17
Nodes (6): The acute:chronic verdict, with the numbers it was read from.…, How far into a taper toward a dated event this session sits., TaperOut, WorkloadOut, The acute:chronic verdict, carrying the summary it was read from. The evidence…, WorkloadAssessment

### Community 53 - "WorkloadState"
Cohesion: 0.15
Nodes (11): The verdict on accumulated load. ``UNKNOWN`` is not ``OPTIMAL``., What to scale an entry's volume target by. Never above 1.0., WorkloadState, The asymmetry the whole design rests on. Being *under* the average is a reason…, Someone whose four-week window is nearly empty is not overreaching by training…, We did not look" and "we looked and it was fine" must not read the same,…, The state that is *not* UNKNOWN and still does nothing -- the engine looked,…, test_a_steady_log_changes_nothing_either() (+3 more)

### Community 54 - "Variation_Context Py"
Cohesion: 0.19
Nodes (12): EquipmentAccess, What the user can actually train with, per environment. Modelled per…, Scheduling constraints and stylistic preferences., TrainingPreferences, Enum, The bridge from the V2 user schema to the engine — M3. This is the first module…, _select_equipment_access(), The user schema must not fork its own equipment enum. (+4 more)

### Community 55 - "assess()"
Cohesion: 0.15
Nodes (13): assess(), The whole scale depends on this. If a steady trainee did not land near 1.0,…, The field is named ``chronic_load_28d`` and holds a weekly figure, which is…, The standard criticism of this ratio, and the reason it is guarded. A two-week-…, A ratio built from a mix of sRPE and kilograms is meaningless rather than…, A blended log is the error that stays silent until someone's training data has…, test_a_doubled_week_is_a_spike_and_backs_the_dose_off(), test_a_log_mixing_two_users_raises() (+5 more)

### Community 56 - "VITE_API_URL"
Cohesion: 0.32
Nodes (11): cleanup(), err(), log(), ok(), run_backend(), run_frontend(), setup_backend(), setup_frontend() (+3 more)

### Community 57 - "VariationContextIn"
Cohesion: 0.17
Nodes (9): The caller-supplied user context, carried by the request itself. There is no…, VariationContextIn, One training occasion, planned or unplanned. Carries ``user_id`` so it stands…, session-RPE x duration in minutes., TrainingSession, Absence of a session and a deliberately skipped one are different facts., test_session_load_is_none_without_rpe(), test_session_load_is_rpe_times_minutes() (+1 more)

### Community 58 - "A fortnight of steady HRV plus one fr..."
Cohesion: 0.17
Nodes (12): A fortnight of steady HRV plus one fresh reading, as JSON a caller would…, M3 pass 2 end to end: the HRV half of the milestone the roadmap parked., The absolute value is identical to the test above. Only this user's own history…, 1.15 x 0.90 = 1.035 would hand an under-recovered user more work than normal.…, The invisible case, on the generation path: asking for a hard session while…, recovery_history(), test_readiness_caps_an_ambitious_request_over_http(), test_session_intent_moves_volume_in_both_directions_over_http() (+4 more)

### Community 59 - "Test_Objective_Strategy Py"
Cohesion: 0.21
Nodes (10): db(), mixed_routine(), fixture, parametrize, The policy is what the whole objective-aware variation rests on, so a strategy…, routine(), test_candidate_rep_schemes_excludes_original_and_stays_in_range(), test_every_strategy_declares_a_variation_policy() (+2 more)

### Community 60 - "@capacitor/cli"
Cohesion: 0.18
Nodes (11): @capacitor/cli, eslint-plugin-react-hooks, globals, devDependencies, @capacitor/cli, eslint-plugin-react-hooks, globals, prettier (+3 more)

### Community 61 - "Chart Tsx"
Cohesion: 0.25
Nodes (9): ChartConfig, ChartContainer, ChartContext, ChartContextProps, ChartLegendContent, ChartTooltipContent, getPayloadConfigFromPayload(), THEMES (+1 more)

### Community 62 - "LoadManagementAssessment"
Cohesion: 0.18
Nodes (6): LoadManagementAssessment, What accumulated load and an upcoming event say about today's volume. A stdlib…, The deeper of the two cuts, never their product. Both terms reduce the same…, Whether the taper, rather than the workload ratio, set the number. Worth…, Every term, binding or not, deepest cut first., Nothing known. Named, so "we did not look" is explicit in the engine.

### Community 63 - "HypertrophyStrategy"
Cohesion: 0.18
Nodes (4): HypertrophyStrategy, Moderate reps and rest -- the muscle-growth-optimised middle ground, and V1's…, The split that matters. Proximity to maximum is what strength adapts to; total…, test_only_strength_preserves_intensity()

### Community 64 - "MuscularEnduranceStrategy"
Cohesion: 0.18
Nodes (4): MuscularEnduranceStrategy, High reps against a light relative load, short rest -- local muscular…, Strength is a movement-specific skill and TrainingMemory is keyed on the…, test_strength_bounds_substitution_far_below_the_others()

### Community 65 - "StrengthStrategy"
Cohesion: 0.18
Nodes (4): Low reps against a heavy relative load, long rest -- maximal-force adaptation., StrengthStrategy, Not zero, deliberately: a hard zero would make a contraindicated lift…, test_strength_still_allows_some_substitution()

### Community 66 - "Training_Memory Py"
Cohesion: 0.31
Nodes (8): _build_record(), datetime, UUID, M8a: what this user has actually done, per exercise. The first module that…, Rebuild every per-exercise record from the session log. ``as_of`` is required…, Rebuild from a whole ``User``. Deliberately recomputed from ``user.sessions``…, Working-set volume load inside a trailing window. Sets missing reps or load…, _volume_within()

### Community 67 - "Variation vs progression tension"
Cohesion: 0.20
Nodes (6): Each objective chooses its variation invariant, Variation vs progression tension, Known gaps (deferred on purpose), What may change between sessions, and what must not., How far an objective lets a prescription move *between* sessions. Deliberately…, VariationPolicy

### Community 68 - "ObjectiveOut"
Cohesion: 0.24
Nodes (8): get, health(), list_objectives(), list_routines(), ObjectiveOut, Lightweight listing entry -- deliberately doesn't resolve exercise names, so…, An implemented objective strategy's parameters, so a caller can render real…, RoutineSummary

### Community 69 - "Library Data Ts"
Cohesion: 0.36
Nodes (8): Effort, Sport, createRoutine(), libraries, routine(), SavedRoutine, starterRoutines, Libreria()

### Community 70 - "Lovable Error Reporting Ts"
Cohesion: 0.24
Nodes (5): LovableErrorOptions, LovableEvents, reportLovableError(), Window, ErrorComponent()

### Community 71 - "Weekday"
Cohesion: 0.20
Nodes (8): Values match ``datetime.date.weekday()`` so the two interoperate., Weekday, AvailabilityWindow, model_validator, A recurring window on one weekday when training is actually possible., test_availability_window_must_be_ordered(), test_weekday_values_match_stdlib_date_weekday(), IntEnum

### Community 72 - "intent_exceeds()"
Cohesion: 0.20
Nodes (6): intent_exceeds(), Whether the user asked for more work than a protective term allowed. Needed…, The user asked for more work than their readiness allowed. See…, The same cancellation by the other route: a hard session asked for during a…, The user asked for more work than their readiness allowed. The rule itself…, The same invisible case by the other route (M8c): a ``CHALLENGING`` session…

### Community 73 - "Six weeks at three sessions a week --..."
Cohesion: 0.31
Nodes (10): Six weeks at three sessions a week -- a ratio of exactly 1.0., The log is posted once. M8b reads it per exercise, M8c reads it per session --…, sprpe_session(), steady_block(), test_a_doubled_week_backs_the_session_off_over_http(), test_a_new_users_ordinary_week_is_not_reported_as_a_spike(), test_a_taper_scales_volume_toward_a_dated_event_over_http(), test_an_ambitious_request_during_a_taper_is_capped_over_http() (+2 more)

### Community 74 - "DurationDoseIn"
Cohesion: 0.28
Nodes (4): DurationDoseIn, DurationDoseOut, DurationDose, Time-under-tension work with no discrete reps: holds, planks, stretches.

### Community 75 - "GenerateSessionRequest"
Cohesion: 0.22
Nodes (6): GenerateSessionRequest, model_validator, The three things a user can answer without owning a programme: how long they…, Reject a difficulty stated twice and differently. ``session_intent`` is a…, A routine, an objective, the engine's tuning knobs, and -- since M3 -- the user…, VaryRequest

### Community 76 - "RoundsDoseIn"
Cohesion: 0.28
Nodes (4): RoundsDoseIn, RoundsDoseOut, Circuit-style work measured in completed rounds, not sets of one exercise --…, RoundsDose

### Community 77 - "best_matches()"
Cohesion: 0.22
Nodes (9): best_matches(), The candidates scoring within ``SUBSTITUTE_SCORE_BAND`` of the best one. A…, The precise claim: the dislike penalty exceeds the tie band, so among…, test_disliked_substitutes_drop_out_of_the_tied_top_band(), The anti-truncation guarantee. Muscle tags are coarse, so candidates tie at the…, The band must be a real filter, not a pass-through -- if enrichment stops…, test_best_matches_is_selective(), test_best_matches_keeps_only_the_top_scoring_band() (+1 more)

### Community 78 - "Breadcrumb Tsx"
Cohesion: 0.25
Nodes (7): Breadcrumb, BreadcrumbEllipsis(), BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator()

### Community 79 - "Drawer Tsx"
Cohesion: 0.25
Nodes (6): DrawerContent, DrawerDescription, DrawerFooter(), DrawerHeader(), DrawerOverlay, DrawerTitle

### Community 80 - "Navigation Menu Tsx"
Cohesion: 0.29
Nodes (7): NavigationMenu, NavigationMenuContent, NavigationMenuIndicator, NavigationMenuList, NavigationMenuTrigger, navigationMenuTriggerStyle, NavigationMenuViewport

### Community 81 - "Select Tsx"
Cohesion: 0.25
Nodes (7): SelectContent, SelectItem, SelectLabel, SelectScrollDownButton, SelectScrollUpButton, SelectSeparator, SelectTrigger

### Community 82 - "LastPerformance"
Cohesion: 0.25
Nodes (3): LastPerformance, The most recent session's working sets for one exercise. Kept separate from…, ``None`` when nothing was prescribed to compare against. Distinguished from…

### Community 83 - "scripts"
Cohesion: 0.29
Nodes (7): scripts, build, build:dev, dev, format, lint, preview

### Community 84 - "Card Tsx"
Cohesion: 0.29
Nodes (6): Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle

### Community 85 - "Objective_Strategy Py"
Cohesion: 0.33
Nodes (6): Invariant, ABC, Enum, str, Objective strategy interface: what each ``TrainingObjective`` wants a set/rep…, What a variation holds constant for the result to still be the same training…

### Community 86 - "_reroll()"
Cohesion: 0.29
Nodes (7): The block's numbers already embody the difficulty, so re-solving them must not…, _reroll(), test_a_block_round_trips_from_generate_into_vary(), test_re_rolling_a_block_preserves_its_volume_and_time_over_http(), test_re_rolling_an_unknown_exercise_is_a_400_not_a_500(), test_re_rolling_applies_no_further_load_scaling_over_http(), test_re_rolling_still_honours_health_constraints_over_http()

### Community 87 - "Health data stays on the device"
Cohesion: 0.33
Nodes (4): Health data stays on the device, Four-tier input resolution, What to scale an entry's volume target by, all in. The inputs **multiply**…, Whether this exercise may be prescribed at all. Inviolable and hard constraints…

### Community 88 - "Exception"
Cohesion: 0.33
Nodes (6): Exception, exception_handler, An unrecognised exercise id is a caller error, not a server fault. It surfaces…, unknown_exercise_handler(), JSONResponse, Request

### Community 89 - "GeneratedSessionOut"
Cohesion: 0.40
Nodes (3): GeneratedSessionOut, GeneratedSession, A session built from scratch, plus the account of how it got that way.…

### Community 90 - "Package Json"
Cohesion: 0.40
Nodes (4): name, private, sideEffects, type

### Community 91 - "Alert Tsx"
Cohesion: 0.50
Nodes (4): Alert, AlertDescription, AlertTitle, alertVariants

### Community 92 - "LoadModulator"
Cohesion: 0.40
Nodes (3): LoadModulator, Anything in the adaptive tier that can scale the volume target. A ``Protocol``…, Protocol

### Community 94 - "A client has to render an intensity-p..."
Cohesion: 0.33
Nodes (4): A client has to render an intensity-preserving objective differently -- the…, Asking for full novelty under a strength objective must not look like the…, test_list_objectives_exposes_the_variation_policy(), test_vary_reports_the_substitution_probability_it_actually_used()

## Knowledge Gaps
- **198 isolated node(s):** `config`, `$schema`, `style`, `rsc`, `tsx` (+193 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **70 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ObjectiveStrategy` connect `ObjectiveStrategy` to `MuscularEnduranceStrategy`, `API Pydantic Schemas`, `StrengthStrategy`, `Variation vs progression tension`, `ObjectiveOut`, `Progression Engine`, `Session Generation Core`, `Biometrics & User Enums`, `Exercise Model & Library Errors`, `Routine Variation`, `Variation Outcomes`, `Objective_Strategy Py`, `FastAPI App Routes`, `Core Domain Models`, `HypertrophyStrategy`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **Why does `VariationContext` connect `Variation Context & Constraints` to `Readiness & Baseline Comparison`, `Session Generation Core`, `Progression Engine`, `Movement Pattern Rules`, `Biometrics & User Enums`, `Exercise Model & Library Errors`, `Routine Variation`, `Fitness Assessment Biometrics`, `Load Management`, `Dose & Routine Entry`, `Variation Outcomes`, `FastAPI App Routes`, `Health Profile & Injuries`, `Engine CLI`, `Core Domain Models`, `API Pydantic Schemas`, `Load Management Tests`, `SessionIntent`, `Test_Load_Management Py`, `WorkloadState`, `Variation_Context Py`, `VariationContextIn`, `LoadManagementAssessment`, `intent_exceeds()`, `best_matches()`, `Health data stays on the device`, `Re-rolling a block drops the adaptive...`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `cn()` connect `shadcn UI Primitives` to `Menubar UI`, `Arcade Game UI`, `Form Input UI Primitives`, `Form UI Components`, `Breadcrumb Tsx`, `Tab Bar & Badge UI`, `Drawer Tsx`, `Navigation Menu Tsx`, `Carousel Tsx`, `Select Tsx`, `Card Tsx`, `Alert Dialog UI`, `Alert Tsx`, `Chart Tsx`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Are the 93 inferred relationships involving `VariationContext` (e.g. with `Health data stays on the device` and `generate()`) actually correct?**
  _`VariationContext` has 93 INFERRED edges - model-reasoned connections that need verification._
- **Are the 75 inferred relationships involving `Muscle` (e.g. with `GenerateSessionRequest` and `GenerationReportOut`) actually correct?**
  _`Muscle` has 75 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `generate_session()` (e.g. with `The engine core stays pure` and `The generator refuses to invent a starting load`) actually correct?**
  _`generate_session()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `vary_routine()` (e.g. with `ExerciseDB` and `ObjectiveStrategy`) actually correct?**
  _`vary_routine()` has 5 INFERRED edges - model-reasoned connections that need verification._