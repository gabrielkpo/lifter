import TopBar from "@/components/TopBar";

/** The coach chat arrives with the agents' orchestration (slice 4). */
export default function CoachPage() {
  return (
    <>
      <TopBar title="Coach" />
      <section className="card">
        <h2>Coming soon</h2>
        <p>
          Talk to the coach: “plan my week”, “move Thursday’s session”, “why this session?”. Every
          change it proposes shows up as a card you approve or reject; nothing changes without
          you.
        </p>
      </section>
    </>
  );
}
