module top (clk, go, abort, last, busy);
  input clk;
  input go;
  input abort;
  output last;
  reg last;
  output busy;
  reg busy;
  parameter S0 = 0;
  parameter S1 = 1;
  parameter S2 = 2;
  parameter S3 = 3;
  parameter S4 = 4;
  parameter S5 = 5;
  parameter S6 = 6;
  parameter S7 = 7;
  parameter S8 = 8;
  parameter S9 = 9;
  parameter S10 = 10;
  parameter S11 = 11;
  parameter S12 = 12;
  parameter S13 = 13;
  parameter S14 = 14;
  parameter S15 = 15;
  (* syn_encoding = "binary" *) reg [3:0] st;
  reg [3:0] ns;
  always @(st or go or abort) begin
    ns = st;
    case (st)
      S0: if (abort) ns = S0; else if (go) ns = S1;
      S1: if (abort) ns = S0; else if (go) ns = S2;
      S2: if (abort) ns = S0; else if (go) ns = S3;
      S3: if (abort) ns = S0; else if (go) ns = S4;
      S4: if (abort) ns = S0; else if (go) ns = S5;
      S5: if (abort) ns = S0; else if (go) ns = S6;
      S6: if (abort) ns = S0; else if (go) ns = S7;
      S7: if (abort) ns = S0; else if (go) ns = S8;
      S8: if (abort) ns = S0; else if (go) ns = S9;
      S9: if (abort) ns = S0; else if (go) ns = S10;
      S10: if (abort) ns = S0; else if (go) ns = S11;
      S11: if (abort) ns = S0; else if (go) ns = S12;
      S12: if (abort) ns = S0; else if (go) ns = S13;
      S13: if (abort) ns = S0; else if (go) ns = S14;
      S14: if (abort) ns = S0; else if (go) ns = S15;
      S15: if (abort) ns = S0; else if (go) ns = S0;
      default: ns = S0;
    endcase
  end
  always @(posedge clk) begin
    st <= ns;
    last <= (ns == S15);
    busy <= (ns != S0);
  end
endmodule
