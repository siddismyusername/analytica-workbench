"use client";

import { Children, isValidElement, type ComponentProps, type ReactNode } from "react";
import { Table } from "@heroui/react";

function nestedChildren(node: ReactNode): ReactNode[] {
  return isValidElement<{ children?: ReactNode }>(node) ? Children.toArray(node.props.children) : [];
}

export function DataTable({ children, className, "aria-label": label }: { children: ReactNode; className?: string; "aria-label": string }) {
  const [head, body] = Children.toArray(children);
  const headerRow = nestedChildren(head)[0];
  const columns = nestedChildren(headerRow);
  const rows = nestedChildren(body);
  const columnItems = columns.map((column, index) => ({ id: `column-${index}`, name: nestedChildren(column).join("") }));

  return (
    <Table className={className}>
      <Table.Content aria-label={label}>
        <Table.Header columns={columnItems}>
          {(column) => <Table.Column id={column.id} isRowHeader={column.id === "column-0"}>{column.name}</Table.Column>}
        </Table.Header>
        <Table.Body>
          {rows.map((row, index) => (
            <Table.Row key={isValidElement(row) ? row.key : index} id={String(index)}>
              {nestedChildren(row).map((cell, cellIndex) => {
                const props = isValidElement<{ className?: string; title?: string; "data-strength"?: string }>(cell) ? cell.props : {};
                return <Table.Cell key={cellIndex} {...(props as ComponentProps<typeof Table.Cell>)}>{nestedChildren(cell)}</Table.Cell>;
              })}
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Content>
    </Table>
  );
}
