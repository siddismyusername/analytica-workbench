"use client";

import { Children, isValidElement, type ComponentProps, type ReactNode } from "react";
import { Button as HeroButton, Input as HeroInput, ListBox, Select as HeroSelect } from "@heroui/react";

type ButtonProps = Omit<ComponentProps<typeof HeroButton>, "isDisabled"> & { disabled?: boolean };

export function Button({ disabled, variant = "tertiary", ...props }: ButtonProps) {
  return <HeroButton {...props} isDisabled={disabled} variant={variant} />;
}

export const Input = HeroInput;

type SelectProps = {
  value: string | number;
  onChange: (event: { target: { value: string } }) => void;
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
};

export function Select({ value, onChange, children, className, ...props }: SelectProps) {
  const options = Children.toArray(children).filter(isValidElement).map((child) => {
    const option = child as React.ReactElement<{ value: string | number; children: ReactNode }>;
    return { value: String(option.props.value), label: option.props.children };
  });

  return (
    <HeroSelect value={String(value)} onChange={(key) => onChange({ target: { value: String(key ?? "") } })} className={className} aria-label={props["aria-label"] ?? "Choose an option"} fullWidth>
      <HeroSelect.Trigger><HeroSelect.Value /><HeroSelect.Indicator /></HeroSelect.Trigger>
      <HeroSelect.Popover><ListBox items={options}>{(option) => <ListBox.Item id={option.value} textValue={String(option.label)}>{option.label}</ListBox.Item>}</ListBox></HeroSelect.Popover>
    </HeroSelect>
  );
}
