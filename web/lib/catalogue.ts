// The PR catalogue: what can hold a personal record, by kind and family. Generic, public
// CrossFit movements and benchmarks, no athlete data. Lift holds the Olympic lifts only:
// strength accessories never get a PR. Until records live in the database (record
// definitions and entries by hand), lift values come from logged sets (/bests) and the other
// kinds show the list without values.

export type RecordType = "rep_max" | "max_reps" | "max_load" | "max_distance" | "max_time" | "time" | "rounds";

export interface Movement {
  name: string;
  /** Other names the exercise bank may use for the same movement. */
  aliases?: string[];
  /** What the record measures; a lift shows its rep maxes. */
  record: RecordType;
  /** Benchmark workout, in one line. */
  description?: string;
}

export interface Family {
  key: string;
  label: string;
  tone: string;
  movements: Movement[];
}

export interface Kind {
  key: "lift" | "gym" | "cardio" | "benchmarks";
  label: string;
  families: Family[];
}

const lift = (name: string, aliases?: string[]): Movement => ({ name, aliases, record: "rep_max" });
const reps = (name: string, aliases?: string[]): Movement => ({ name, aliases, record: "max_reps" });
const time = (name: string, description?: string): Movement => ({ name, record: "time", description });
const rounds = (name: string, description: string): Movement => ({
  name,
  record: "rounds",
  description,
});

export const CATALOGUE: Kind[] = [
  {
    key: "lift",
    label: "Lift",
    families: [
      {
        key: "clean",
        label: "Cleans",
        tone: "--blue",
        movements: [
          lift("Clean", ["Squat clean"]),
          lift("Power clean"),
          lift("Hang clean"),
          lift("Hang power clean"),
          lift("Hang squat clean"),
          lift("Muscle clean"),
          lift("Clean pull"),
          lift("Clean and jerk", ["Clean & jerk"]),
        ],
      },
      {
        key: "snatch",
        label: "Snatches",
        tone: "--red",
        movements: [
          lift("Snatch", ["Squat snatch"]),
          lift("Power snatch"),
          lift("Hang snatch"),
          lift("Hang power snatch"),
          lift("Hang squat snatch"),
          lift("Muscle snatch"),
          lift("Snatch balance"),
          lift("Snatch pull"),
          lift("Overhead squat"),
        ],
      },
      {
        key: "jerk",
        label: "Jerks",
        tone: "--green",
        movements: [
          lift("Push jerk"),
          lift("Split jerk"),
          lift("Power jerk"),
          lift("Squat jerk"),
          lift("Push jerk behind the neck", ["Behind the neck push jerk"]),
          lift("Split jerk behind the neck", ["Behind the neck split jerk"]),
          lift("Push press"),
        ],
      },
    ],
  },
  {
    key: "gym",
    label: "Gym",
    families: [
      {
        key: "max_reps",
        label: "Max reps",
        tone: "--red",
        movements: [
          reps("Pull-ups", ["Pull-up", "Kipping pull-up"]),
          reps("Strict pull-ups", ["Strict pull-up"]),
          reps("Chest-to-bar", ["Chest to bar"]),
          reps("Strict chest-to-bar"),
          reps("Bar muscle-ups", ["Bar muscle-up"]),
          reps("Ring muscle-ups", ["Ring muscle-up"]),
          reps("Toes-to-bar", ["Toes to bar"]),
          reps("Handstand push-ups", ["HSPU"]),
          reps("Strict handstand push-ups", ["Strict HSPU"]),
          reps("Ring dips", ["Ring dip"]),
          reps("Dips"),
          reps("Push-ups", ["Push-up"]),
          reps("Pistols", ["Pistol squat"]),
          reps("Double unders", ["Double under"]),
        ],
      },
      {
        key: "max_load",
        label: "1RM",
        tone: "--blue",
        movements: [
          { name: "Weighted pull-up", record: "max_load" },
          { name: "Weighted dip", record: "max_load" },
          { name: "Weighted chin-up", record: "max_load" },
        ],
      },
      {
        key: "max_distance",
        label: "Max distance",
        tone: "--amber",
        movements: [{ name: "Handstand walk", record: "max_distance" }],
      },
      {
        key: "max_time",
        label: "Max time",
        tone: "--green",
        movements: [
          { name: "Handstand hold", record: "max_time" },
          { name: "L-sit hold", record: "max_time" },
          { name: "Dead hang", record: "max_time" },
        ],
      },
    ],
  },
  {
    key: "cardio",
    label: "Cardio",
    families: [
      {
        key: "run",
        label: "Run",
        tone: "--red",
        movements: ["400 m", "800 m", "1 km", "1 mile", "2 km", "5 km", "10 km", "Half marathon", "Marathon"].map(
          (d) => time(`${d} run`),
        ),
      },
      {
        key: "row",
        label: "Row",
        tone: "--blue",
        movements: ["500 m", "1 km", "2 km", "5 km", "10 km"].map((d) => time(`${d} row`)),
      },
      {
        key: "ski",
        label: "Ski erg",
        tone: "--amber",
        movements: ["500 m", "1 km", "2 km", "5 km"].map((d) => time(`${d} ski erg`)),
      },
      {
        key: "bike",
        label: "Assault bike",
        tone: "--green",
        movements: [
          time("50 cal assault bike"),
          time("100 cal assault bike"),
          { name: "Max cal 1 min assault bike", record: "max_reps" },
          { name: "Max cal 10 min assault bike", record: "max_reps" },
        ],
      },
    ],
  },
  {
    key: "benchmarks",
    label: "Benchmarks",
    families: [
      {
        key: "girls",
        label: "Girls",
        tone: "--red",
        movements: [
          time("Fran", "21-15-9 thrusters 43/30 kg, pull-ups"),
          time("Grace", "30 clean and jerks 61/43 kg"),
          time("Isabel", "30 snatches 61/43 kg"),
          time("Diane", "21-15-9 deadlifts 102/70 kg, handstand push-ups"),
          time("Elizabeth", "21-15-9 squat cleans 61/43 kg, ring dips"),
          time("Helen", "3 rounds: 400 m run, 21 KB swings 24/16 kg, 12 pull-ups"),
          time("Karen", "150 wall balls 9/6 kg"),
          time("Annie", "50-40-30-20-10 double unders, sit-ups"),
          time("Jackie", "1000 m row, 50 thrusters 20/15 kg, 30 pull-ups"),
          time("Nancy", "5 rounds: 400 m run, 15 overhead squats 43/30 kg"),
          time("Amanda", "9-7-5 ring muscle-ups, squat snatches 61/43 kg"),
          time("Angie", "100 pull-ups, 100 push-ups, 100 sit-ups, 100 squats"),
          rounds("Cindy", "AMRAP 20 min: 5 pull-ups, 10 push-ups, 15 squats"),
          rounds("Mary", "AMRAP 20 min: 5 HSPU, 10 pistols, 15 pull-ups"),
          rounds("Chelsea", "EMOM 30 min: 5 pull-ups, 10 push-ups, 15 squats"),
        ],
      },
      {
        key: "heroes",
        label: "Heroes",
        tone: "--blue",
        movements: [
          time("Murph", "1.6 km run, 100 pull-ups, 200 push-ups, 300 squats, 1.6 km run"),
          time("DT", "5 rounds: 12 deadlifts, 9 hang power cleans, 6 push jerks 70/47 kg"),
          time("JT", "21-15-9 handstand push-ups, ring dips, push-ups"),
          time("Michael", "3 rounds: 800 m run, 50 back extensions, 50 sit-ups"),
          time("Randy", "75 power snatches 34/25 kg"),
        ],
      },
    ],
  },
];

/** The movement's name as the exercise bank may write it, for matching logged bests. */
export function matches(movement: Movement, exercise: string): boolean {
  const name = exercise.trim().toLowerCase();
  return [movement.name, ...(movement.aliases ?? [])].some((n) => n.toLowerCase() === name);
}
