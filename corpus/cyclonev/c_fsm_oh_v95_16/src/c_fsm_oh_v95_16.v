module c_fsm_oh_v95_16 (clk, rst, go, alt, done, odd);
  input clk, rst, go, alt;
  output done, odd;
  parameter S0 = 16'b0000000000000001;
  parameter S1 = 16'b0000000000000010;
  parameter S2 = 16'b0000000000000100;
  parameter S3 = 16'b0000000000001000;
  parameter S4 = 16'b0000000000010000;
  parameter S5 = 16'b0000000000100000;
  parameter S6 = 16'b0000000001000000;
  parameter S7 = 16'b0000000010000000;
  parameter S8 = 16'b0000000100000000;
  parameter S9 = 16'b0000001000000000;
  parameter S10 = 16'b0000010000000000;
  parameter S11 = 16'b0000100000000000;
  parameter S12 = 16'b0001000000000000;
  parameter S13 = 16'b0010000000000000;
  parameter S14 = 16'b0100000000000000;
  parameter S15 = 16'b1000000000000000;
  reg [15:0] st;
  reg [15:0] nx;
  always @(st or go or alt) begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S4;
        else nx = S3;
      end
      S4: begin
        if (go) nx = S5;
        else nx = S4;
      end
      S5: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S6;
        else nx = S5;
      end
      S6: begin
        if (go) nx = S7;
        else nx = S6;
      end
      S7: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S8;
        else nx = S7;
      end
      S8: begin
        if (go) nx = S9;
        else nx = S8;
      end
      S9: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S10;
        else nx = S9;
      end
      S10: begin
        if (go) nx = S11;
        else nx = S10;
      end
      S11: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S12;
        else nx = S11;
      end
      S12: begin
        if (go) nx = S13;
        else nx = S12;
      end
      S13: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S14;
        else nx = S13;
      end
      S14: begin
        if (go) nx = S15;
        else nx = S14;
      end
      S15: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S15;
      end
      default: nx = S0;
    endcase
  end
  always @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S15);
  assign odd = (st == S1) | (st == S3) | (st == S5) | (st == S7) | (st == S9) | (st == S11) | (st == S13) | (st == S15);
endmodule
