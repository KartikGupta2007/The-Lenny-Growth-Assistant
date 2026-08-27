/**
 * Episode titles in the corpus embed the guest, e.g.
 * "A framework for finding product-market fit | Todd Jackson (First Round)".
 * The guest is shown separately, so the display title drops that tail.
 */
export function episodeName(title: string): string {
  const head = title.split('|')[0].trim();
  return head.length > 0 ? head : title;
}
