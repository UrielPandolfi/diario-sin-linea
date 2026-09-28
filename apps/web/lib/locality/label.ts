export type LocalityLabel = {
  name: string;
  province_name: string;
  department_name?: string;
  show_department: boolean;
};

export function localityLabel(place: LocalityLabel): string {
  if (place.show_department && place.department_name) {
    return `${place.name}, ${place.department_name}, ${place.province_name}`;
  }
  return `${place.name}, ${place.province_name}`;
}
