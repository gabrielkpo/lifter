import TopBar from "@/components/TopBar";

/** The athlete's profile: rules, equipment, preferences come with the profile step. */
export default function ProfilePage() {
  return (
    <>
      <TopBar title="Profile" />
      <section className="card">
        <h2>Athlete</h2>
        <p>
          Injuries, preferred and avoided exercises, equipment and availability will live here,
          read by the coach before it plans.
        </p>
      </section>
    </>
  );
}
