import { BrandLogo } from "./BrandLogo";

/**
 * Logo for sign-in splash screens. The tagline appears only at 640px and
 * wider (Tailwind `sm`), where it renders at its natural 13px size. Below
 * that, a smaller logo without the tagline is shown. The hidden variant is
 * display:none, so only one is exposed to assistive tech at a time.
 */
export function BrandSplash() {
  return (
    <div className="flex justify-center" data-testid="brand-splash">
      <BrandLogo className="h-20 w-auto sm:hidden" />
      <BrandLogo tagline className="hidden h-40 w-auto sm:block" />
    </div>
  );
}
