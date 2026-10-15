// The app mark: a white "L" on the app's black, drawn by next/og for the icons.
export default function Mark({ size }: { size: number }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#121212",
        color: "#ffffff",
        fontSize: size * 0.56,
        fontWeight: 800,
      }}
    >
      L
    </div>
  );
}
