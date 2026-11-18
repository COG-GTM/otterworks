export function getTimeOfDayGreeting(date: Date = new Date()): string {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}

export function getGreeting(displayName?: string | null, date: Date = new Date()): string {
  const greeting = getTimeOfDayGreeting(date);
  const name = displayName?.trim();
  return name ? `${greeting}, ${name}` : greeting;
}
